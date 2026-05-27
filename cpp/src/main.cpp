// Runs cpp data pipeline
// Modes:
//   normalize_data <input.csv> <output.csv> <symbol> <interval>
//   normalize_data --batch <raw_dir> <processed_dir>
//   normalize_data --merge <incoming_raw_dir> <processed_dir>
//   normalize_data --normalize-processed <processed_dir>

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include "bar_record.hpp"
#include "validate.hpp"

namespace fs = std::filesystem;

namespace {

struct ProcessStats {
    std::size_t rows_written = 0;
    std::size_t rows_skipped = 0;
};

struct MergeStats {
    std::size_t existing_rows = 0;
    std::size_t incoming_rows = 0;
    std::size_t final_rows = 0;
    std::size_t duplicates_removed = 0;
    std::size_t conflict_rows = 0;
    std::size_t skipped_rows = 0;
};

struct FileMeta {
    std::string symbol;
    std::string interval;
};

std::string trim(const std::string& s) {
    std::size_t start = 0;
    while (start < s.size() && std::isspace(static_cast<unsigned char>(s[start]))) {
        ++start;
    }

    std::size_t end = s.size();
    while (end > start && std::isspace(static_cast<unsigned char>(s[end - 1]))) {
        --end;
    }

    std::string out = s.substr(start, end - start);

    if (out.size() >= 2 && out.front() == '"' && out.back() == '"') {
        out = out.substr(1, out.size() - 2);
    }

    return out;
}

std::string normalize_timestamp(const std::string& input) {
    std::string ts = trim(input);

    // Canonical project timestamp format:
    // 2026-05-08T13:40:00Z
    // This converts 2026-05-08T13:40:00.000Z to 2026-05-08T13:40:00Z.
    const std::size_t dot_pos = ts.find('.');
    const std::size_t z_pos = ts.find('Z');

    if (dot_pos != std::string::npos && z_pos != std::string::npos && dot_pos < z_pos) {
        ts = ts.substr(0, dot_pos) + "Z";
    }

    return ts;
}

std::string bar_key(const BarRecord& bar) {
    return bar.symbol + "|" + normalize_timestamp(bar.ts) + "|" + bar.interval;
}

bool same_ohlcv(const BarRecord& a, const BarRecord& b) {
    return a.open == b.open
        && a.high == b.high
        && a.low == b.low
        && a.close == b.close
        && a.volume == b.volume;
}


std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string current;
    bool in_quotes = false;

    for (char ch : line) {
        if (ch == '"') {
            in_quotes = !in_quotes;
            current += ch;
        } else if (ch == ',' && !in_quotes) {
            fields.push_back(trim(current));
            current.clear();
        } else {
            current += ch;
        }
    }

    fields.push_back(trim(current));
    return fields;
}

std::string strip_commas(const std::string& s) {
    std::string out;
    out.reserve(s.size());

    for (char ch : s) {
        if (ch != ',') {
            out += ch;
        }
    }

    return out;
}

std::vector<std::string> split_on_underscore(const std::string& s) {
    std::vector<std::string> parts;
    std::string current;

    for (char ch : s) {
        if (ch == '_') {
            if (!current.empty()) {
                parts.push_back(current);
                current.clear();
            }
        } else {
            current += ch;
        }
    }

    if (!current.empty()) {
        parts.push_back(current);
    }

    return parts;
}

FileMeta infer_meta_from_filename(const fs::path& path) {
    const std::string stem = path.stem().string();
    const std::vector<std::string> parts = split_on_underscore(stem);

    if (parts.size() < 2) {
        throw std::runtime_error("Could not infer symbol and interval from filename: " + path.filename().string() + ". Expected something like AAPL_5min_raw.csv or AAPL_5min_update.csv");
    }

    return FileMeta{parts[0], parts[1]};
}

std::unordered_map<std::string, std::size_t> build_header_map(const std::vector<std::string>& header) {
    std::unordered_map<std::string, std::size_t> index_map;

    for (std::size_t i = 0; i < header.size(); ++i) {
        index_map[header[i]] = i;
    }

    return index_map;
}

std::string get_required_field(const std::vector<std::string>& row, const std::unordered_map<std::string, std::size_t>& header_map, const std::string& column_name) {
    auto it = header_map.find(column_name);
    if (it == header_map.end()) {
        throw std::runtime_error("Missing required column in header: " + column_name);
    }

    const std::size_t idx = it->second;
    if (idx >= row.size()) {
        throw std::runtime_error("Row is missing field for column: " + column_name);
    }

    return row[idx];
}

bool is_valid_bar(const BarRecord& bar) {
    if (bar.open <= 0 || bar.high <= 0 || bar.low <= 0 || bar.close <= 0) {
        return false;
    }

    if (bar.high < bar.open || bar.high < bar.close) {
        return false;
    }

    if (bar.low > bar.open || bar.low > bar.close) {
        return false;
    }

    if (bar.volume < 0) {
        return false;
    }

    return true;
}

BarRecord normalize_raw_row(const std::vector<std::string>& row, const std::unordered_map<std::string, std::size_t>& header_map, const std::string& symbol, const std::string& interval) {
    const std::string ts = normalize_timestamp(get_required_field(row, header_map, "Date"));
    const std::string open_str = get_required_field(row, header_map, "Open");
    const std::string high_str = get_required_field(row, header_map, "High");
    const std::string low_str = get_required_field(row, header_map, "Low");
    const std::string close_str = get_required_field(row, header_map, "Close");
    const std::string volume_str = get_required_field(row, header_map, "Volume");

    const std::string cleaned_volume = strip_commas(volume_str);

    BarRecord bar{
        symbol,
        ts,
        std::stod(open_str),
        std::stod(high_str),
        std::stod(low_str),
        std::stod(close_str),
        std::stoll(cleaned_volume),
        interval
    };

    return bar;
}

BarRecord parse_processed_row(const std::vector<std::string>& row, const std::unordered_map<std::string, std::size_t>& header_map) {
    BarRecord bar{
        get_required_field(row, header_map, "symbol"),
        normalize_timestamp(get_required_field(row, header_map, "ts")),
        std::stod(get_required_field(row, header_map, "open")),
        std::stod(get_required_field(row, header_map, "high")),
        std::stod(get_required_field(row, header_map, "low")),
        std::stod(get_required_field(row, header_map, "close")),
        std::stoll(strip_commas(get_required_field(row, header_map, "volume"))),
        get_required_field(row, header_map, "interval")
    };

    return bar;
}

std::vector<BarRecord> read_raw_bars(const fs::path& input_path, const std::string& symbol, const std::string& interval, std::size_t& skipped_count) {
    std::ifstream in(input_path);
    if (!in.is_open()) {
        throw std::runtime_error("Could not open input file: " + input_path.string());
    }

    std::string header_line;
    if (!std::getline(in, header_line)) {
        throw std::runtime_error("Input file is empty: " + input_path.string());
    }

    const auto header = split_csv_line(header_line);
    const auto header_map = build_header_map(header);

    std::vector<BarRecord> bars;
    std::string line;
    std::size_t line_number = 1;

    while (std::getline(in, line)) {
        ++line_number;

        if (trim(line).empty()) {
            continue;
        }

        try {
            const auto row = split_csv_line(line);
            BarRecord bar = normalize_raw_row(row, header_map, symbol, interval);

            if (!is_valid_bar(bar)) {
                ++skipped_count;
                std::cerr << "Skipping invalid bar in " << input_path << " at line " << line_number << '\n';
                continue;
            }

            bars.push_back(bar);
        } catch (const std::exception& e) {
            ++skipped_count;
            std::cerr << "Skipping line " << line_number << " in " << input_path << ": " << e.what() << '\n';
        }
    }

    std::sort(bars.begin(), bars.end(), [](const BarRecord& a, const BarRecord& b) {
        return a.ts < b.ts;
    });

    return bars;
}

std::vector<BarRecord> read_processed_bars(const fs::path& input_path, std::size_t& skipped_count) {
    std::vector<BarRecord> bars;

    if (!fs::exists(input_path)) {
        return bars;
    }

    std::ifstream in(input_path);
    if (!in.is_open()) {
        throw std::runtime_error("Could not open processed file: " + input_path.string());
    }

    std::string header_line;
    if (!std::getline(in, header_line)) {
        return bars;
    }

    const auto header = split_csv_line(header_line);
    const auto header_map = build_header_map(header);

    std::string line;
    std::size_t line_number = 1;

    while (std::getline(in, line)) {
        ++line_number;

        if (trim(line).empty()) {
            continue;
        }

        try {
            const auto row = split_csv_line(line);
            BarRecord bar = parse_processed_row(row, header_map);

            if (!is_valid_bar(bar)) {
                ++skipped_count;
                std::cerr << "Skipping invalid processed bar in " << input_path << " at line " << line_number << '\n';
                continue;
            }

            bars.push_back(bar);
        } catch (const std::exception& e) {
            ++skipped_count;
            std::cerr << "Skipping line " << line_number << " in " << input_path << ": " << e.what() << '\n';
        }
    }

    std::sort(bars.begin(), bars.end(), [](const BarRecord& a, const BarRecord& b) {
        return a.ts < b.ts;
    });

    return bars;
}

void write_normalized_header(std::ofstream& out) {
    out << "symbol,ts,open,high,low,close,volume,interval\n";
}

void write_bar(std::ofstream& out, const BarRecord& bar) {
    out << bar.symbol << ',' << bar.ts << ',' << bar.open << ',' << bar.high << ',' << bar.low << ',' << bar.close << ',' << bar.volume << ',' << bar.interval << '\n';
}

void write_bars(const fs::path& output_path, const std::vector<BarRecord>& bars) {
    fs::create_directories(output_path.parent_path());

    std::ofstream out(output_path);
    if (!out.is_open()) {
        throw std::runtime_error("Could not open output file: " + output_path.string());
    }

    write_normalized_header(out);
    for (const auto& bar : bars) {
        write_bar(out, bar);
    }
}

std::vector<BarRecord> dedupe_existing_bars_keep_first(
    const std::vector<BarRecord>& bars,
    std::size_t& duplicates_removed,
    std::size_t& conflict_rows
) {
    // Used for --normalize-processed.
    // If duplicate keys exist inside a processed file, the first existing row wins.
    std::map<std::string, BarRecord> by_key;

    for (auto bar : bars) {
        bar.ts = normalize_timestamp(bar.ts);
        const std::string key = bar_key(bar);

        auto [it, inserted] = by_key.insert({key, bar});
        if (!inserted) {
            ++duplicates_removed;
            if (!same_ohlcv(it->second, bar)) {
                ++conflict_rows;
                std::cerr << "Conflict inside processed file, kept first row for " << key << '\n';
            }
        }
    }

    std::vector<BarRecord> deduped;
    deduped.reserve(by_key.size());

    for (const auto& [key, bar] : by_key) {
        deduped.push_back(bar);
    }

    std::sort(deduped.begin(), deduped.end(), [](const BarRecord& a, const BarRecord& b) {
        if (a.symbol != b.symbol) return a.symbol < b.symbol;
        if (a.ts != b.ts) return a.ts < b.ts;
        return a.interval < b.interval;
    });

    return deduped;
}

std::vector<BarRecord> merge_keep_existing(
    const std::vector<BarRecord>& existing,
    const std::vector<BarRecord>& incoming,
    std::size_t& duplicates_removed,
    std::size_t& conflict_rows
) {
    // Existing processed rows win. Incoming rows only fill missing keys.
    std::map<std::string, BarRecord> by_key;

    for (auto bar : existing) {
        bar.ts = normalize_timestamp(bar.ts);
        const std::string key = bar_key(bar);

        auto [it, inserted] = by_key.insert({key, bar});
        if (!inserted) {
            ++duplicates_removed;
            if (!same_ohlcv(it->second, bar)) {
                ++conflict_rows;
                std::cerr << "Conflict inside existing processed data, kept first row for " << key << '\n';
            }
        }
    }

    for (auto bar : incoming) {
        bar.ts = normalize_timestamp(bar.ts);
        const std::string key = bar_key(bar);

        auto [it, inserted] = by_key.insert({key, bar});
        if (!inserted) {
            ++duplicates_removed;
            if (!same_ohlcv(it->second, bar)) {
                ++conflict_rows;
                std::cerr << "Conflict kept existing for " << key << '\n';
            }
        }
    }

    std::vector<BarRecord> merged;
    merged.reserve(by_key.size());

    for (const auto& [key, bar] : by_key) {
        merged.push_back(bar);
    }

    std::sort(merged.begin(), merged.end(), [](const BarRecord& a, const BarRecord& b) {
        if (a.symbol != b.symbol) return a.symbol < b.symbol;
        if (a.ts != b.ts) return a.ts < b.ts;
        return a.interval < b.interval;
    });

    return merged;
}

fs::path processed_path_for(const fs::path& processed_dir, const FileMeta& meta) {
    return processed_dir / (meta.symbol + "_" + meta.interval + "_processed.csv");
}

ProcessStats normalize_single_file(const fs::path& input_path, const fs::path& output_path, const std::string& symbol, const std::string& interval) {
    std::size_t skipped = 0;
    auto bars = read_raw_bars(input_path, symbol, interval, skipped);
    write_bars(output_path, bars);

    std::cout << "\nInput file:   " << input_path.string() << '\n';
    std::cout << "Output file:  " << output_path.string() << '\n';
    std::cout << "Symbol:       " << symbol << '\n';
    std::cout << "Interval:     " << interval << '\n';
    std::cout << "Rows written: " << bars.size() << '\n';
    std::cout << "Rows skipped: " << skipped << '\n';

    return ProcessStats{bars.size(), skipped};
}

MergeStats merge_single_file(const fs::path& incoming_raw_path, const fs::path& processed_path, const std::string& symbol, const std::string& interval) {
    std::size_t skipped = 0;
    auto existing = read_processed_bars(processed_path, skipped);
    auto incoming = read_raw_bars(incoming_raw_path, symbol, interval, skipped);

    std::size_t duplicates_removed = 0;
    std::size_t conflict_rows = 0;
    auto merged = merge_keep_existing(existing, incoming, duplicates_removed, conflict_rows);
    write_bars(processed_path, merged);

    std::cout << "\nIncoming file:      " << incoming_raw_path.string() << '\n';
    std::cout << "Processed target:   " << processed_path.string() << '\n';
    std::cout << "Symbol:             " << symbol << '\n';
    std::cout << "Interval:           " << interval << '\n';
    std::cout << "Existing rows:      " << existing.size() << '\n';
    std::cout << "Incoming rows:      " << incoming.size() << '\n';
    std::cout << "Final rows:         " << merged.size() << '\n';
    std::cout << "Duplicates removed: " << duplicates_removed << '\n';
    std::cout << "Conflicts kept:     " << conflict_rows << '\n';
    std::cout << "Rows skipped:       " << skipped << '\n';

    return MergeStats{existing.size(), incoming.size(), merged.size(), duplicates_removed, conflict_rows, skipped};
}

bool is_csv_file(const fs::path& path) {
    return fs::is_regular_file(path) && path.extension() == ".csv";
}

int run_batch_mode(const fs::path& raw_dir, const fs::path& processed_dir) {
    if (!fs::exists(raw_dir) || !fs::is_directory(raw_dir)) {
        throw std::runtime_error("Raw directory does not exist: " + raw_dir.string());
    }

    fs::create_directories(processed_dir);

    std::size_t files_processed = 0;
    std::size_t files_failed = 0;
    std::size_t total_written = 0;
    std::size_t total_skipped = 0;

    for (const auto& entry : fs::directory_iterator(raw_dir)) {
        const fs::path input_path = entry.path();
        if (!is_csv_file(input_path)) {
            continue;
        }

        try {
            const FileMeta meta = infer_meta_from_filename(input_path);
            const fs::path output_path = processed_path_for(processed_dir, meta);
            const ProcessStats stats = normalize_single_file(input_path, output_path, meta.symbol, meta.interval);

            ++files_processed;
            total_written += stats.rows_written;
            total_skipped += stats.rows_skipped;
        } catch (const std::exception& e) {
            ++files_failed;
            std::cerr << "Failed to process " << input_path << ": " << e.what() << '\n';
        }
    }

    std::cout << "\nBatch summary\n";
    std::cout << "-------------\n";
    std::cout << "Files processed: " << files_processed << '\n';
    std::cout << "Files failed:    " << files_failed << '\n';
    std::cout << "Rows written:    " << total_written << '\n';
    std::cout << "Rows skipped:    " << total_skipped << '\n';

    return files_failed == 0 ? 0 : 1;
}

int run_merge_mode(const fs::path& incoming_dir, const fs::path& processed_dir) {
    if (!fs::exists(incoming_dir) || !fs::is_directory(incoming_dir)) {
        throw std::runtime_error("Incoming directory does not exist: " + incoming_dir.string());
    }

    fs::create_directories(processed_dir);

    std::size_t files_merged = 0;
    std::size_t files_failed = 0;
    std::size_t total_existing = 0;
    std::size_t total_incoming = 0;
    std::size_t total_final = 0;
    std::size_t total_dupes = 0;
    std::size_t total_conflicts = 0;
    std::size_t total_skipped = 0;

    for (const auto& entry : fs::directory_iterator(incoming_dir)) {
        const fs::path incoming_path = entry.path();
        if (!is_csv_file(incoming_path)) {
            continue;
        }

        try {
            const FileMeta meta = infer_meta_from_filename(incoming_path);
            const fs::path target_path = processed_path_for(processed_dir, meta);
            const MergeStats stats = merge_single_file(incoming_path, target_path, meta.symbol, meta.interval);

            ++files_merged;
            total_existing += stats.existing_rows;
            total_incoming += stats.incoming_rows;
            total_final += stats.final_rows;
            total_dupes += stats.duplicates_removed;
            total_conflicts += stats.conflict_rows;
            total_skipped += stats.skipped_rows;
        } catch (const std::exception& e) {
            ++files_failed;
            std::cerr << "Failed to merge " << incoming_path << ": " << e.what() << '\n';
        }
    }

    std::cout << "\nMerge summary\n";
    std::cout << "-------------\n";
    std::cout << "Files merged:       " << files_merged << '\n';
    std::cout << "Files failed:       " << files_failed << '\n';
    std::cout << "Existing rows read: " << total_existing << '\n';
    std::cout << "Incoming rows read: " << total_incoming << '\n';
    std::cout << "Final rows total:   " << total_final << '\n';
    std::cout << "Duplicates removed: " << total_dupes << '\n';
    std::cout << "Conflicts kept:     " << total_conflicts << '\n';
    std::cout << "Rows skipped:       " << total_skipped << '\n';

    return files_failed == 0 ? 0 : 1;
}

int run_normalize_processed_mode(const fs::path& processed_dir) {
    if (!fs::exists(processed_dir) || !fs::is_directory(processed_dir)) {
        throw std::runtime_error("Processed directory does not exist: " + processed_dir.string());
    }

    std::size_t files_normalized = 0;
    std::size_t files_failed = 0;
    std::size_t total_rows_before = 0;
    std::size_t total_rows_after = 0;
    std::size_t total_dupes = 0;
    std::size_t total_conflicts = 0;
    std::size_t total_skipped = 0;

    for (const auto& entry : fs::directory_iterator(processed_dir)) {
        const fs::path path = entry.path();
        if (!is_csv_file(path)) {
            continue;
        }

        try {
            std::size_t skipped = 0;
            auto existing = read_processed_bars(path, skipped);

            std::size_t duplicates_removed = 0;
            std::size_t conflict_rows = 0;
            auto normalized = dedupe_existing_bars_keep_first(existing, duplicates_removed, conflict_rows);

            write_bars(path, normalized);

            ++files_normalized;
            total_rows_before += existing.size();
            total_rows_after += normalized.size();
            total_dupes += duplicates_removed;
            total_conflicts += conflict_rows;
            total_skipped += skipped;

            std::cout << "\nProcessed file:     " << path.string() << '\n';
            std::cout << "Rows before:        " << existing.size() << '\n';
            std::cout << "Rows after:         " << normalized.size() << '\n';
            std::cout << "Duplicates removed: " << duplicates_removed << '\n';
            std::cout << "Conflicts kept:     " << conflict_rows << '\n';
            std::cout << "Rows skipped:       " << skipped << '\n';
        } catch (const std::exception& e) {
            ++files_failed;
            std::cerr << "Failed to normalize processed file " << path << ": " << e.what() << '\n';
        }
    }

    std::cout << "\nNormalize processed summary\n";
    std::cout << "---------------------------\n";
    std::cout << "Files normalized:   " << files_normalized << '\n';
    std::cout << "Files failed:       " << files_failed << '\n';
    std::cout << "Rows before:        " << total_rows_before << '\n';
    std::cout << "Rows after:         " << total_rows_after << '\n';
    std::cout << "Duplicates removed: " << total_dupes << '\n';
    std::cout << "Conflicts kept:     " << total_conflicts << '\n';
    std::cout << "Rows skipped:       " << total_skipped << '\n';

    return files_failed == 0 ? 0 : 1;
}

void print_usage() {
    std::cerr
        << "Usage:\n"
        << "  normalize_data <input.csv> <output.csv> <symbol> <interval>\n"
        << "  normalize_data --batch <raw_dir> <processed_dir>\n"
        << "  normalize_data --merge <incoming_raw_dir> <processed_dir>\n"
        << "  normalize_data --normalize-processed <processed_dir>\n"
        << "  normalize_data --validate <processed_dir>\n\n"
        << "Examples:\n"
        << "  normalize_data data/raw/AAPL_5min_raw.csv data/processed/AAPL_5min_processed.csv AAPL 5min\n"
        << "  normalize_data --batch data/raw data/processed\n"
        << "  normalize_data --merge data/raw/live data/processed\n"
        << "  normalize_data --normalize-processed data/processed\n"
        << "  normalize_data --validate data/processed\n";
}

} // namespace

int main(int argc, char* argv[]) {
    try {
        if (argc == 3 && std::string(argv[1]) == "--validate") {
            return run_validate_mode(argv[2]);
        }

        if (argc == 3 && std::string(argv[1]) == "--normalize-processed") {
            return run_normalize_processed_mode(argv[2]);
        }

        if (argc == 4 && std::string(argv[1]) == "--batch") {
            return run_batch_mode(argv[2], argv[3]);
        }

        if (argc == 4 && std::string(argv[1]) == "--merge") {
            return run_merge_mode(argv[2], argv[3]);
        }

        if (argc == 5) {
            normalize_single_file(argv[1], argv[2], argv[3], argv[4]);
            return 0;
        }

        print_usage();
        return 1;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << '\n';
        return 1;
    }
}
