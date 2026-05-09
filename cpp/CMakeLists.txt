cmake_minimum_required(VERSION 3.16)

project(IntradayQuantCpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(normalize_data
    src/main.cpp
    src/validate.cpp
)

target_include_directories(normalize_data PRIVATE include)