# Publication notes

Publish the sanitized repository contents as a new Git history. Keep the original engineering reference archive and private working copies outside the public repository.

Before the first push:

1. Review the exact files selected for the commit. Exclude local credentials, provisioned firmware headers, `.local/`, virtual environments, databases and their WAL/SHM files, captures, private logs, and model artifacts.
2. Confirm configuration examples contain only blank credentials or placeholders.
3. Review names, contact information, photographs, logos, addresses, and site-specific network details for intended public use.
4. Run the software checks and record their actual result. Keep physical and research claims within the limits described in [SOURCE-STATUS.md](SOURCE-STATUS.md).
5. Regenerate published checksums from the finished public copy. Checksums from the original archive do not describe modified files.
6. Decide the intended project license before describing the repository as open source.

## License status

No project `LICENSE` file was included in the supplied archive. This sanitization does not choose or add a project license. The copyright holder needs to decide the intended license and confirm the rights to included material.

Third-party dependencies and toolchains retain their own license terms. See [current-gateway/THIRD_PARTY.md](current-gateway/THIRD_PARTY.md). The public source copy does not include dependency wheels or the ESP32 toolchain.

## Future changes

Keep real credentials and laboratory data outside the repository. Review every proposed commit before publication, including generated files. A clean source copy does not sanitize files added later.
