#ifdef FROM_ANVIL_CXXFLAGS
#error C++ flags must not be passed to C sources
#endif

int anvil_c_support(void) {
    return 0;
}