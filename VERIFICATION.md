# Verification of the public source copy

Checked October 18, 2026 on macOS with Python 3.12.14. Gateway dependencies were installed in an isolated work directory from the supplied lockfile with required package hashes. No packages or test data are bundled in this repository.

| Check | Result |
| --- | --- |
| Gateway Python suite | 195 tests passed |
| LED firmware native host check | Passed |
| Vehicle motor-engine native host check | Passed |
| Python syntax, including extensionless utilities | 47 files passed |
| Bash syntax | 19 scripts passed |
| JavaScript syntax | 22 files passed |
| SVG parsing and privacy review | 16 assets passed; no embedded scripts, external references, or creator metadata |
| Git exclusions | 29 private examples excluded; 24 public examples retained |
| Observer arguments | Help works without BCC; missing, malformed, and duplicate addresses are rejected |
| Duplicated instructor check utilities | Byte-identical after configuration change |
| Configuration templates | Existing release-policy checks passed |
| Gateway integrity manifest | Regenerated and verified for this copy |
| Final public archive | Checksums, member contents, CRCs, paths, and normalized metadata verified |
| Original reference | All 178 source files and the original ZIP remained unchanged |

Run the software checks from current-gateway/:

~~~sh
python tools/verify_bundle.py
python tools/test.py
~~~

Verify the full delivered source inventory from the repository root:

~~~sh
shasum -a 256 -c SHA256SUMS
~~~

SHA256SUMS covers the delivered files except itself. Regenerate integrity records after intentional source changes. A checksum establishes file identity, not security or deployment qualification.

The first public-copy test run passed 194 of 195 Python tests. Its remaining failure identified an inherited omission: the car page lacked the physical-validation notice already required by the UI test. The notice was restored; the final run passed all 195 tests and both native checks. The existing test assertion was preserved.

Independent source reviews found no apparent real credentials and no remaining personal contacts, exact lab location, account paths, or original deployment addresses. Standard loopback/RFC1918 validation values and neutral synthetic test addresses remain.

These checks use software, mocked transport, or native host firmware engines. No Raspberry Pi connection, service change, firmware flash, live eBPF capture, physical experiment, AI effectiveness evaluation, or formal research validation occurred. The supplied Observer decoder issue remains documented in [SOURCE-STATUS.md](SOURCE-STATUS.md).
