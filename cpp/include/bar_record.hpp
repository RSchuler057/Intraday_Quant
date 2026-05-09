#pragma once

#include <string>

struct BarRecord {
    std::string symbol;
    std::string ts;
    double open;
    double high;
    double low;
    double close;
    long long volume;
    std::string interval;
};