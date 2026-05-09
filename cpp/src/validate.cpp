#include "validate.hpp"

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

namespace fs = std::filesystem;

namespace {

struct TimestampParts {
    std::string date;
    int hour = 0;
    int minute = 0;
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

std::unordered_map<std::string, std::size_t> build_header_map(
    const std::vector<std::string>& header
) {
    std::unordered_map<std::string, std::size_t> index_map;

    for (std::size_t i = 0; i < header.size(); ++i) {
        index_map[header[i]] = i;
    }

    return index_map;
}

std::string get_required_field(
    const std::vector<std::string>& row,
    const std::unordered_map<std::string, std::size_t>& header_map,
    const std::string& column_name
) {
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

BarRecord processed_row_to_bar(
    const std::vector<std::string>& row,
    const std::unordered_map<std::string, std::size_t>& header_map
) {
    return BarRecord{
        get_required_field(row, header_map, "symbol"),
        get_required_field(row, header_map, "ts"),
        std::stod(get_required_field(row, header_map, "open")),
        std::stod(get_required_field(row, header_map, "high")),
        std::stod(get_required_field(row, header_map, "low")),
        std::stod(get_required_field(row, header_map, "close")),
        std::stoll(get_required_field(row, header_map, "volume")),
        get_required_field(row, header_map, "interval")
    };
}

std::vector<BarRecord> read_processed_bars(
    const fs::path& processed_path,
    std::size_t& skipped_rows
) {
    std::ifstream in(processed_path);
    if (!in.is_open()) {
        throw std::runtime_error("Could not open processed file: " + processed_path.string());
    }

    std::string header_line;
    if (!std::getline(in, header_line)) {
        throw std::runtime_error("Processed file is empty: " + processed_path.string());
    }

    const auto header = split_csv_line(header_line);
    const auto header_map = build_header_map(header);

    std::vector<BarRecord> bars;
    std::string line;
    std::size_t line_number = 1;

    while (std::getline(in, line)) {
        ++line_number;
        if (line.empty()) {
            continue;
        }

        try {
            const auto row = split_csv_line(line);
            bars.push_back(processed_row_to_bar(row, header_map));
        } catch (const std::exception& e) {
            ++skipped_rows;
            std::cerr << "Skipping processed line " << line_number
                      << " in " << processed_path.filename().string()
                      << ": " << e.what() << '\n';
        }
    }

    return bars;
}

int interval_to_minutes(const std::string& interval) {
    if (interval.size() < 4 || interval.substr(interval.size() - 3) != "min") {
        throw std::runtime_error(
            "Unsupported interval format: " + interval +
            ". Expected something like 5min or 10min."
        );
    }

    return std::stoi(interval.substr(0, interval.size() - 3));
}

TimestampParts parse_timestamp_parts(const std::string& ts) {
    // Expected examples:
    //   2026-01-02T14:30:00.000Z
    //   2026-01-02T14:30:00Z
    if (ts.size() < 16 || ts[4] != '-' || ts[7] != '-' || ts[10] != 'T' || ts[13] != ':') {
        throw std::runtime_error("Unsupported timestamp format: " + ts);
    }

    TimestampParts parts;
    parts.date = ts.substr(0, 10);
    parts.hour = std::stoi(ts.substr(11, 2));
    parts.minute = std::stoi(ts.substr(14, 2));
    return parts;
}

int minutes_since_midnight(const std::string& ts) {
    const TimestampParts parts = parse_timestamp_parts(ts);
    return parts.hour * 60 + parts.minute;
}

std::string date_from_ts(const std::string& ts) {
    return parse_timestamp_parts(ts).date;
}

std::size_t expected_bars_per_regular_session(const std::string& interval) {
    const int minutes = interval_to_minutes(interval);
    if (minutes <= 0) {
        throw std::runtime_error("Interval minutes must be positive.");
    }

    // Regular US equity session is 390 minutes: 9:30 AM to 4:00 PM ET.
    // If bars are timestamped at bar start, this gives 78 bars for 5min and 39 bars for 10min.
    return static_cast<std::size_t>(390 / minutes);
}

bool is_csv_file(const fs::path& path) {
    return fs::is_regular_file(path) && path.extension() == ".csv";
}

} // namespace

ValidateStats validate_processed_file(
    const fs::path& processed_path,
    std::size_t max_examples
) {
    std::size_t skipped = 0;
    const auto bars = read_processed_bars(processed_path, skipped);

    ValidateStats stats;
    stats.rows_read = bars.size();
    stats.skipped_rows = skipped;

    if (bars.empty()) {
        std::cout << "\nValidation file: " << processed_path.string() << '\n';
        std::cout << "Rows read:       0\n";
        std::cout << "Status:          EMPTY\n";
        return stats;
    }

    const std::string interval = bars.front().interval;
    const int expected_delta = interval_to_minutes(interval);
    const std::size_t expected_per_day = expected_bars_per_regular_session(interval);

    std::map<std::string, std::size_t> counts_by_day;
    std::map<std::string, std::string> first_ts_by_day;
    std::map<std::string, std::string> last_ts_by_day;
    std::map<std::string, std::string> seen_timestamps;

    std::vector<std::string> gap_examples;
    std::vector<std::string> duplicate_examples;
    std::vector<std::string> partial_day_examples;

    for (std::size_t i = 0; i < bars.size(); ++i) {
        const auto& bar = bars[i];
        const std::string day = date_from_ts(bar.ts);

        ++counts_by_day[day];
        if (!first_ts_by_day.count(day)) {
            first_ts_by_day[day] = bar.ts;
        }
        last_ts_by_day[day] = bar.ts;

        auto [it, inserted] = seen_timestamps.insert({bar.ts, bar.ts});
        if (!inserted) {
            ++stats.duplicates;
            if (duplicate_examples.size() < max_examples) {
                duplicate_examples.push_back(bar.ts);
            }
        }

        if (i == 0) {
            continue;
        }

        const auto& prev = bars[i - 1];
        if (bar.ts < prev.ts) {
            ++stats.ordering_issues;
        }

        const std::string prev_day = date_from_ts(prev.ts);
        if (day == prev_day) {
            const int prev_minutes = minutes_since_midnight(prev.ts);
            const int curr_minutes = minutes_since_midnight(bar.ts);
            const int delta = curr_minutes - prev_minutes;

            if (delta > expected_delta) {
                ++stats.same_day_gaps;
                const int missing = (delta / expected_delta) - 1;
                if (missing > 0) {
                    stats.likely_missing_bars += static_cast<std::size_t>(missing);
                }

                if (gap_examples.size() < max_examples) {
                    gap_examples.push_back(
                        prev.ts + " -> " + bar.ts + " (" + std::to_string(delta) + " min)"
                    );
                }
            } else if (delta <= 0) {
                ++stats.ordering_issues;
            }
        }
    }

    stats.days_seen = counts_by_day.size();

    for (const auto& [day, count] : counts_by_day) {
        if (count < expected_per_day) {
            ++stats.potential_partial_days;
            if (partial_day_examples.size() < max_examples) {
                partial_day_examples.push_back(
                    day + " count=" + std::to_string(count) +
                    " first=" + first_ts_by_day[day] +
                    " last=" + last_ts_by_day[day]
                );
            }
        }
    }

    std::cout << "\nValidation file:        " << processed_path.string() << '\n';
    std::cout << "Symbol:                 " << bars.front().symbol << '\n';
    std::cout << "Interval:               " << interval << '\n';
    std::cout << "Rows read:              " << stats.rows_read << '\n';
    std::cout << "Days seen:              " << stats.days_seen << '\n';
    std::cout << "Expected full-day bars: " << expected_per_day << '\n';
    std::cout << "Duplicate timestamps:   " << stats.duplicates << '\n';
    std::cout << "Ordering issues:        " << stats.ordering_issues << '\n';
    std::cout << "Same-day gaps:          " << stats.same_day_gaps << '\n';
    std::cout << "Likely missing bars:    " << stats.likely_missing_bars << '\n';
    std::cout << "Potential partial days: " << stats.potential_partial_days << '\n';
    std::cout << "Rows skipped on read:   " << stats.skipped_rows << '\n';

    if (!gap_examples.empty()) {
        std::cout << "Gap examples:\n";
        for (const auto& ex : gap_examples) {
            std::cout << "  - " << ex << '\n';
        }
    }

    if (!duplicate_examples.empty()) {
        std::cout << "Duplicate examples:\n";
        for (const auto& ex : duplicate_examples) {
            std::cout << "  - " << ex << '\n';
        }
    }

    if (!partial_day_examples.empty()) {
        std::cout << "Potential partial-day examples:\n";
        for (const auto& ex : partial_day_examples) {
            std::cout << "  - " << ex << '\n';
        }
    }

    return stats;
}

int run_validate_mode(const fs::path& processed_dir) {
    if (!fs::exists(processed_dir) || !fs::is_directory(processed_dir)) {
        throw std::runtime_error("Processed directory does not exist: " + processed_dir.string());
    }

    std::size_t files_checked = 0;
    std::size_t files_failed = 0;
    ValidateStats total;

    for (const auto& entry : fs::directory_iterator(processed_dir)) {
        const fs::path path = entry.path();
        if (!is_csv_file(path)) {
            continue;
        }

        try {
            const ValidateStats stats = validate_processed_file(path);
            ++files_checked;
            total.rows_read += stats.rows_read;
            total.duplicates += stats.duplicates;
            total.ordering_issues += stats.ordering_issues;
            total.same_day_gaps += stats.same_day_gaps;
            total.likely_missing_bars += stats.likely_missing_bars;
            total.potential_partial_days += stats.potential_partial_days;
            total.days_seen += stats.days_seen;
            total.skipped_rows += stats.skipped_rows;
        } catch (const std::exception& e) {
            ++files_failed;
            std::cerr << "Failed to validate " << path << ": " << e.what() << '\n';
        }
    }

    std::cout << "\nValidation summary\n";
    std::cout << "------------------\n";
    std::cout << "Files checked:          " << files_checked << '\n';
    std::cout << "Files failed:           " << files_failed << '\n';
    std::cout << "Rows read:              " << total.rows_read << '\n';
    std::cout << "Days seen:              " << total.days_seen << '\n';
    std::cout << "Duplicate timestamps:   " << total.duplicates << '\n';
    std::cout << "Ordering issues:        " << total.ordering_issues << '\n';
    std::cout << "Same-day gaps:          " << total.same_day_gaps << '\n';
    std::cout << "Likely missing bars:    " << total.likely_missing_bars << '\n';
    std::cout << "Potential partial days: " << total.potential_partial_days << '\n';
    std::cout << "Rows skipped on read:   " << total.skipped_rows << '\n';

    return files_failed == 0 ? 0 : 1;
}
