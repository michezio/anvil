cmake_minimum_required(VERSION 3.16)
project(anvil_cmake_flags_project LANGUAGES C CXX)

# Keep whatever CMake initializes (including env-provided CXXFLAGS) and append project flags.
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DFROM_CMAKELISTS_GLOBAL=1")
set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -DFROM_CMAKELISTS_RELEASE=1")

add_executable(anvil_cmake_flags main.cpp support.c)
