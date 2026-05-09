#pragma once

#include <cstddef>
#include <filesystem>

struct ValidateStats {
    std::size_t rows_read = 0;
    std::size_t duplicates = 0;
    std::size_t ordering_issues = 0;
    std::size_t same_day_gaps = 0;
    std::size_t likely_missing_bars = 0;
    std::size_t potential_partial_days = 0;
    std::size_t days_seen = 0;
    std::size_t skipped_rows = 0;
};

ValidateStats validate_processed_file(
    const std::filesystem::path& processed_path,
    std::size_t max_examples = 5
);

int run_validate_mode(const std::filesystem::path& processed_dir);
