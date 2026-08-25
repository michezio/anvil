#ifndef FROM_ANVIL_CXXFLAGS
#error FROM_ANVIL_CXXFLAGS must come from anvil variant cxx_flags
#endif

#ifndef FROM_ANVIL_DEFINES
#error FROM_ANVIL_DEFINES must come from anvil variant defines
#endif

#ifndef FROM_CMAKELISTS_GLOBAL
#error FROM_CMAKELISTS_GLOBAL must come from CMakeLists global flags
#endif

#ifdef ANVIL_EXPECT_RELEASE
#ifndef FROM_CMAKELISTS_RELEASE
#error FROM_CMAKELISTS_RELEASE must come from CMAKE_CXX_FLAGS_RELEASE for Release builds
#endif
#endif

int main() {
    return 0;
}