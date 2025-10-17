#include <openssl/evp.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>

extern "C" int hash_file(const char* algo_name, const char* file_path, char* out, size_t out_len) {
    OpenSSL_add_all_digests();
    const EVP_MD* md = EVP_get_digestbyname(algo_name);
    if (!md) {
        return 1;
    }
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) return 1;
    std::ifstream file(file_path, std::ios::binary);
    if (!file) {
        EVP_MD_CTX_free(ctx);
        return 1;
    }
    EVP_DigestInit_ex(ctx, md, nullptr);
    char buf[4096];
    while (file.read(buf, sizeof(buf)) || file.gcount()) {
        EVP_DigestUpdate(ctx, buf, file.gcount());
    }
    unsigned char hash[EVP_MAX_MD_SIZE];
    unsigned int len;
    EVP_DigestFinal_ex(ctx, hash, &len);
    EVP_MD_CTX_free(ctx);
    if (out_len < len * 2 + 1) return 1;
    for (unsigned int i = 0; i < len; ++i)
        std::sprintf(out + i * 2, "%02x", hash[i]);
    out[len * 2] = '\0';
    return 0;
}

#ifdef BUILD_CLI
int main(int argc, char* argv[]) {
    if (argc != 3) {
        std::cerr << "usage: " << argv[0] << " <algo> <file>\n";
        return 1;
    }
    char out[EVP_MAX_MD_SIZE * 2 + 1];
    if (hash_file(argv[1], argv[2], out, sizeof(out)) != 0) {
        return 1;
    }
    std::cout << out << "\n";
    return 0;
}
#endif
