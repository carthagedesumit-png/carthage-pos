# Controlled Pilot Acceptance Checklist

Release candidate: `1.0.0-rc.2`. Physical evidence must come from the designated clean Windows 11 PC and real devices. Never infer a pass from mocks. Use `PASS`, `FAIL`, or `BLOCKED`; all rows below remain `BLOCKED / physically unverified` until executed.

For every row record: responsible tester, execution date, status, evidence file/reference, and defect reference (or `none`). Evidence must omit passwords, tokens, payment secrets, and customer data.

| Acceptance item | Prerequisite | Steps | Expected result | Evidence to capture |
|---|---|---|---|---|
| Fresh Windows 11 install | Clean designated PC; approved installer | Verify installer checksum; install without existing CBOS data | Integrity passes; install completes only in selected locations | OS/build, checksum output, installer log excerpt |
| First run and administrator | Fresh install | Launch; complete setup; sign in; change bootstrap password | One active store/admin; forced change enforced | Redacted setup and login screenshots |
| Store, users, and roles | Admin login | Configure store; create cashier and manager; test permissions | Roles and store boundaries enforced server-side | User/role matrix and denied-action evidence |
| Product and barcode | Manager login | Create active product, stock it, assign barcode | Identifier is unique and product is sellable | Product/barcode screenshots |
| Keyboard scanner | Configured USB keyboard-wedge scanner | Scan known, unknown, inactive, unavailable, out-of-stock, repeated, and rapid codes | Known adds correct item; intentional repeats increase quantity; invalid states are clear; no checkout is triggered | Scanner model, timing notes, cart screenshots |
| Payments and split tender | Open cash session; stocked product | Complete cash, card/POS, transfer, and supported split sales | One committed sale/payment set per submission; references are masked | Receipt numbers and redacted payment summaries |
| 58 mm receipt | Configured 58 mm printer and paper | Test print; sell; disconnect/reconnect; retry | Layout readable; failure is non-destructive and retryable | Printer model, photo, audit event, receipt number |
| 80 mm receipt | Configured 80 mm printer and paper | Repeat 58 mm scenarios | Correct deterministic 80 mm layout | Printer model, photo, audit event |
| Historical reprint | Manager/admin; completed sale | Reprint after restart | Marked reprint; audit created; no sale/payment/stock/report mutation | Original/reprint photos and before/after totals |
| Cash drawer | Compatible printer-connected drawer | Cash sale; non-cash sale; authorized manual open with reason; disconnect | Opens only when eligible/authorized; failures do not undo sale | Drawer model, audit rows, test notes |
| Refund and stock restoration | Completed sale; manager | Partial and full supported refunds | Authorization, refund, stock, and reports remain consistent | Credit note, stock and report snapshots |
| Cash reconciliation | Open cash session with test sales | Close and reconcile session | Expected/actual/variance rules enforced | Redacted reconciliation report |
| Reports | Completed sales/refunds | Run sales, payment, inventory, finance reports | Totals agree with transactions | Export/screenshot references |
| Backup and isolated restore | Writable backup path; isolated restore directory | Create, verify, restore copy, compare | Backup verifies; restored copy is compatible | Verification output and isolated paths redacted |
| Restart recovery | Active cart and committed sale | Restart before commit, after commit, and after print failure | Cart resumes safely; committed sale remains; reprint works | Cart/sale IDs and recovery screenshots |
| Offline operation | Local host installation | Disconnect internet/LAN where safe; sell and reprint locally | Local workflow continues without internet | Network state and transaction evidence |
| Upgrade rehearsal | Copy of supported RC database; isolated directories | Run repository upgrade rehearsal only | Historical data retained; compatibility passes | Rehearsal report and checksums |
| Uninstall/data retention | Disposable pilot PC backup | Exercise retain/remove choices | Choice is explicit and matches documented behavior | Uninstall screenshots and retained-path check |
| Peripheral failures | Real configured devices | Offline, paper-out, cancellation, timeout/blocked queue, invalid config | Actionable safe errors; no duplicate financial mutation | Photos, logs, audit IDs, receipt numbers |
| Clean-second-PC validation | Designated second PC available | Repeat install through uninstall checklist | Independent result recorded | Complete evidence bundle |

Sign-off: pilot owner ___; security reviewer ___; finance reviewer ___; support owner ___; decision ___; open defects ___; rollback owner ___; date ___.

Current status: every physical row is `BLOCKED / physically unverified` because the designated computer and real peripherals are unavailable. Automated fake-device tests are supporting evidence only.
