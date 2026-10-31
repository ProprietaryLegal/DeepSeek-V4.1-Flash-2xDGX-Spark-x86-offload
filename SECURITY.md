# Security

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting
("Report a vulnerability" on the Security tab of this repository).

Relevant areas include the persistent prefix tier's isolation between namespaces (its code follows in the next push), the RDMA
services on the x86 host (`offload/engram/server/`, `offload/dspark/worker/`), and the API firewall rule (`firewall.sh`).
The Engram server and drafter worker are meant to listen only on private point-to-point links; do not expose them to
other networks.
