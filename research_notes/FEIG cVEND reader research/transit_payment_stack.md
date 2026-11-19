# FEIG cVEND Transit/Payment Application Stack

Scope: Public documentation of the fare-media and payment schemes a FEIG cVEND validator
handles (EMVCo contactless, ITSO, Girogo, VDV-KA, account-based ticketing), mapped against the
reverse-engineered cVEND firmware 02.35 whose enabled "ProxCard" handlers are VdvKa(4),
MifareClassic(5), Iso(6), Desfire(7), Girogo(8), Itso(9), UltralightC(10), plus
`emvco_ep_configure` / `emvco_ep_preprocess` and an `EmvReader`.

Note on sourcing: FEIG's own product claims are vendor-reported marketing; EMVCo Book A/B
normative text was not retrievable in full (the spec PDFs are behind emvco.com document search),
so entry-point mechanics below are drawn from patent filings that cite Book A tables plus
secondary summaries, and are flagged accordingly.

---

## Q1. EMVCo Level 2 "Entry Point" kernel: emvco_ep_configure / emvco_ep_preprocess, and why EMV polling needs config

### Takeaway
The firmware symbols `emvco_ep_configure` / `emvco_ep_preprocess` correspond directly to the EMVCo
Book B "Entry Point" — the terminal-side state machine that polls for a contactless card, runs
Pre-Processing (Entry Point sub-process that evaluates the transaction amount against per-scheme
limits), performs Combination Selection (matching the card's AID + Kernel ID to a configured
"reader combination"), and activates the matching Level 2 kernel. The Entry Point cannot run
without configuration data: each supported card brand must be provisioned as a "reader
combination" with its AID, Kernel ID, and transaction limits, which is why an EMV-capable reader
"won't start" EMV polling until a config object exists. (Documented as concept; exact Book B
wording not retrieved.)

### Cited Findings
- EMVCo's Entry Point Specification is "an interoperable terminal specification that lets a single
  terminal process contactless payments regardless of the payment application the card supports."
  — [WebSearch synthesis of EMVCo Entry Point](https://www.emvco.com/processes-category/kernel-id/)
- The **Kernel ID is defined in Book B** and "defines a one-to-one matching between the card
  application and the contactless kernel in the reader." — [EMVCo Kernel ID page](https://www.emvco.com/processes-category/kernel-id/)
- Entry Point **Pre-Processing** sets indicators "per reader Combination (AID–Kernel ID) as defined
  in Book A, Table 5-3," and those indicators are passed to the selected kernel. — [US Patent 11107055 (cites EMV Book A)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11107055)
- Each **reader Combination may have a set of Entry Point Configuration Data, as defined in Table
  5-2 of Book A**, and "all elements defined in this table are optional." — [US Patent 11138583](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11138583)
- A contactless transaction "may begin at **Start A** or **Start B** depending on whether the
  transaction amount is variable or not"; pre-processing is the start for variable-amount
  transactions and fixed-amount transactions can begin later, skipping pre-processing. — [US Patent 11138583](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11138583)
- The EMV kernel is "the software that point-of-sale terminals and ATMs use to process contactless
  transactions"; a kernel "can co-exist with [other] kernels in existing payment acceptance
  terminals and readers." — [EMVCo knowledge hub](https://www.emvco.com/knowledge-hub/4-key-features-of-the-new-emv-contactless-kernel-specification/)
- Pre-Processing evaluates the amount against per-combination limits such as the **Contactless
  Transaction Limit**, **CVM Required Limit**, and **Floor Limit**; above the CVM limit cardholder
  verification (PIN/signature/biometric/CDCVM) is required, below the floor limit the transaction
  can be accepted without going online. — [Wikipedia: Contactless payment](https://en.wikipedia.org/wiki/Contactless_payment)
- Transit terminals may use **non-standard polling sequences** (e.g. a Type A signal followed by
  two Type B signals) and are advised to handle "card clash" by disabling UID-clash logic or
  lowering polling speed. — [US Patent 11734669 (mass transit access)](https://patents.google.com/patent/US11734669); [Google Wallet open-loop transit requirements](https://developers.google.com/wallet/tickets/open-loop/technical-integration/basic-requirements)

### Inferences
- `emvco_ep_configure` is almost certainly the routine that loads/validates the Entry Point
  Configuration Data (the set of reader combinations: AID + Kernel ID + limits per brand). If no
  valid combination set is configured, the Entry Point has nothing to match a card against, which
  explains firmware behavior where EMV polling "won't start without a config." (Inference from
  Book A Table 5-2 "Configuration Data" semantics.)
- `emvco_ep_preprocess` maps to Book B Pre-Processing: it runs the per-combination amount checks
  and sets the indicators (e.g. "status check requested," "zero amount," "CVM required," "online
  required") before the card is even selected — consistent with the Start A / Start B split.
- For open-loop transit specifically, the amount at tap time is typically zero or a nominal "tap"
  amount (fare computed later by the back office), so the reader is likely configured so Pre-
  Processing treats it as a zero-amount / deferred-authorization flow rather than a fixed retail
  sale. (Inference; not directly confirmed in retrieved sources.)
- The `EmvReader` symbol is likely the firmware's wrapper that owns the Entry Point + one or more
  Level 2 kernels, parallel to the "ProxCard" handlers that own the closed-loop schemes.

### Gaps
- Could not retrieve EMV Book B / Book A normative text directly (emvco.com gates the PDFs behind
  document search). Table 5-2 / 5-3 contents are known only via patent paraphrase.
- No source explicitly ties the FEIG firmware function names to EMVCo nomenclature; the mapping is
  inference based on the exact "entry point / pre-process" terminology match.

---

## Q2. ITSO (UK interoperable smart ticketing): cards, HOPS, DESFire carriage

### Takeaway
ITSO is the UK's national technical specification for interoperable smart ticketing. The ticketing
application is the **ITSO Shell** living on customer media (smartcard or phone); products/entitlements
are **IPEs**; security is enforced by an **ISAM**; and the back office is the **HOPS** (Host
Operator or Processing System). Part 10 maps the logical Shell onto physical card platforms,
including DESFire (DESFire support/placeholders are in the current Part 10 revision).

### Cited Findings
- ITSO Specification **Version 2.1.5** is "a UK technical platform for interoperable smart
  ticketing… defines the interfaces needed for smart media, terminals, back offices, and separate
  ticketing systems to work together." — [ITSO technical specification](https://www.itso.org.uk/itso-specification/itso-technical-specification)
- **ITSO Shell** = the application on the card (Part 2); the three-layer model separates the
  customer's card/device, the Shell, and the product stored within it. — [ITSO spec page](https://www.itso.org.uk/itso-specification/itso-technical-specification)
- **IPEs (ITSO Product Entities)** are the core product concept (Part 1); Part 5 specifies standard
  IPEs such as period passes and entitlement products, with value records and transaction logs. — [ITSO spec page](https://www.itso.org.uk/itso-specification/itso-technical-specification)
- **ISAM (ITSO Secure Application Module)** runs within terminals and back-office systems and,
  with the ISMS, "protect[s] every transaction through encryption and authentication" (Parts 7/8). — [ITSO spec page](https://www.itso.org.uk/itso-specification/itso-technical-specification)
- **HOPS (Host Operator or Processing System)** = the ITSO back office; "processes transactions,
  manages products and accounts, and maintains the security of the ITSO environment." Part 4 is the
  HOPS specification. — [ITSO spec page](https://www.itso.org.uk/itso-specification/itso-technical-specification); [ITSO Part 4 HOPS](https://www.itso.org.uk/download/42205.8/part-4-hops)
- **Part 10 (Customer Media Definitions)** "maps the logical ITSO Shell structure onto specific
  card technologies, covering memory layouts and command interactions," distinguishing full vs
  compact ITSO Shell implementations by media capability. Current version 2.1.5, dated 2025-03-31.
  Its revision history adds "placeholders for DESFire and Calypso," and it lists "Mifare Standard
  1K as obsolete." — [ITSO spec page](https://www.itso.org.uk/itso-specification/itso-technical-specification); [ITSO Part 10](https://www.itso.org.uk/download/42069.3/part-10-customer-media-definitions)
- The 2.1.5 update adds "support for DESFire card emulation in Apple Wallet… enhanced contactless
  polling (v2.3), and acceptance of CMD11 and CMD12 commands." — [ITSO Part 10 / release notes](https://www.itso.org.uk/itso-specification/itso-technical-specification)
- Real-world DESFire migration: TfL moved Oyster off hack-prone MIFARE Classic toward DESFire;
  cards hold both Oyster and the ITSO application. — [NFC Times](https://nfctimes.com/news/transport-london-discard-mifare-classic-seeks-desfire-sims)

### Inferences
- On the cVEND reader, the `Itso(9)` handler implements the ITSO Shell read/verify flow: select the
  ITSO Shell on the card (on DESFire this is a DESFire application/file set per Part 10), use the
  ISAM to authenticate/validate the IPEs, and log the transaction. The reader needs an ISAM
  (FEIG's SAM sockets — see Q5) to do ITSO security. (Inference consistent with ITSO architecture.)
- ITSO-on-DESFire means the `Itso(9)` and `Desfire(7)` handlers overlap at the chip level: DESFire
  is the physical platform, ITSO Shell is the logical application carried in DESFire files. The
  separate `Desfire(7)` handler likely covers generic/other DESFire applications (e.g. VDV-KA is
  also DESFire-based — see Q4).

### Gaps
- Could not retrieve the Part 10 DESFire file/AID layout (which DESFire AID, file IDs, key
  settings carry the ITSO Shell). Part 10 is public PDF but was not fetched.
- Whether cVEND's DESFire-based ITSO is "full" or "compact" Shell is not documented in retrieved
  sources.

---

## Q3. Girogo (German prepaid contactless)

### Takeaway
Girogo is a discontinued German contactless prepaid (stored-value) purse function that ran on the
GeldKarte chip of Sparkassen/bank cards over NFC (ISO 14443 / 13.56 MHz). It was a closed, offline,
on-card balance scheme — not an open-loop EMV payment. It was wound down 2020–2024/2025.

### Cited Findings
- Girogo is "a contactless prepaid payment function on Sparkassen-Cards (debit cards)"; "GeldKarte
  technology handles contact payments, while girogo technology handles contactless ones." — [Sparkasse GeldKarte FAQ](https://www.sparkasse.de/unsere-loesungen/privatkunden/karten/geldkarte.html)
- Balance is **stored on the chip**, must be loaded beforehand (typically at an ATM), usual limit
  ~€200 per top-up; card must be held <4 cm from the reader. — [CIO.de girogo](https://www.cio.de/article/3668857/kontaktloses-bezahlen-mit-girogo.html)
- GeldKarte dates to 1996; the prepaid girogo variant has existed since the 2012 introduction of
  NFC cards. — [Wikipedia: GeldKarte](https://en.wikipedia.org/wiki/GeldKarte)
- **Discontinued**: the GeldKarte/girogo function was phased out starting 1 July 2020; remaining
  cards lose validity 31 Dec 2024; acceptance at non-Sparkasse points possible until 30 June 2025.
  Wikipedia states the system was abandoned in December 2024. — [Sparkasse FAQ](https://www.sparkasse.de/unsere-loesungen/privatkunden/karten/geldkarte.html); [Wikipedia: GeldKarte](https://en.wikipedia.org/wiki/GeldKarte)

### Inferences
- The `Girogo(8)` handler reads the on-card stored-value purse (select the GeldKarte/girogo
  application over ISO 14443, read balance, perform the offline purse debit with scheme keys —
  likely needing a SAM). Because girogo is now defunct, this handler on firmware 02.35 is likely a
  legacy/German-market capability that is dormant in current deployments. (Inference.)

### Gaps
- No retrieved source documents the girogo command set / APDU-level purse-debit protocol or its key
  management (would require the German ZKA/Deutsche Kreditwirtschaft "GeldKarte" spec).

---

## Q4. VDV-KA / (((eTicket Deutschland

### Takeaway
VDV-KA (VDV-Kernapplikation / "VDV Core Application") is Germany's national interoperable transit
e-ticketing standard, branded (((eTicket Deutschland, first released 2005. The ticketing
entitlement is the **Berechtigung** (EFS = Elektronischer Fahrschein, stored in TLV format), with
an **application logbook**; it runs on microprocessor smartcards over contact (ISO 7816) or
contactless (ISO/IEC 14443) interfaces. MIFARE DESFire is a common carrier platform, though the
original reference chips were higher-end microcontrollers (NXP SmartMX with RSA) — DESFire usage is
documented for the ecosystem but the exact certified-chip mapping was not pinned down.

### Cited Findings
- VDV-KA was "first released in 2005 by a company set up to develop the (((eTicket Deutschland
  brand," and has been developed further since. — [Intelligent Transport](https://www.intelligenttransport.com/transport-articles/10003/eticket-germany/)
- The VDV Core Application "can run on chip cards using a high-performance microprocessor and
  standard contact or contactless interfaces (ISO 7816 / ISO 14443)." — [Intelligent Transport (2005)](https://www.intelligenttransport.com/transport-articles/1559/e-ticketing-in-germany/)
- An eTicket fare transaction is stored "on the chip card, in the **Berechtigung** (authorization)
  and in the **application logbook**" (Applikationslogbuch). — [VDV control-verification doc, 2017 (German)](https://media.frag-den-staat.de/files/foi/565526/20171122KontrollnachweiseEFS_geschwaerzt.pdf)
- Inspection generates **control records (TXEBER/TXEMBER)** carrying a MAC as a tamper check, plus
  a sequence-number check (berLogSeqNummer) to confirm no transactions are missing. — [VDV control-verification doc, 2017](https://media.frag-den-staat.de/files/foi/565526/20171122KontrollnachweiseEFS_geschwaerzt.pdf)
- The EFS uses a **TLV format**; the Deutschlandticket technical requirements describe a
  "Multi-Berechtigung" variant needing an authentication key (KID 30, organisation ID 5900) in the
  key store, and a tag 0xD6 "sceId." — [KCD-NRW Technische Anforderung Deutschlandticket V1.4/V1.9](https://www.kcd-nrw.de/fileadmin/user_upload/Technische_Anforderung_Deutschlandticket_V1.4.pdf)
- NXP supplied **SmartMX** contactless microcontrollers for VDV-KA, meeting VDV security
  requirements "including RSA-based public key cryptography." — [NS Energy / NXP](https://www.nsenergybusiness.com/)
- MIFARE DESFire EV1/EV3 is ISO/IEC 14443 Type A, ISO 14443-4 transmission, used widely in German
  transit (fare purses, access/time recording, up to ~28 applications on EV1). — [NXP DESFire EV3 datasheet](https://www.crz.gov.sk//data/att/4664173.pdf); [InterCard DESFire EV1 (2009)](https://www.unimagazin.ovgu.de/unimagdeburg_media/Studium/Studierende/Info_DES_Fire-p-3343.pdf)
- A successor standard "eTiCore" is due from 2027. — [TED notice 228926-2026](https://ted.europa.eu/en/notice/228926-2026/pdf)

### Inferences
- The `VdvKa(4)` handler selects the VDV-KA application on the card (DESFire-hosted in most modern
  deployments), reads the Berechtigung/EFS (TLV), validates its MAC/signature using a SAM-held key,
  and writes the application logbook / control record on validation. This is why `VdvKa(4)` and
  `Desfire(7)` again overlap: DESFire is the carrier, VDV-KA the logical application. (Inference
  consistent with the Berechtigung/logbook model above.)
- VDV-KA on the reader needs the VDV key hierarchy in a SAM (the TXEBER/TXEMBER MAC and KID-based
  keys imply symmetric key material the validator must hold securely).

### Gaps
- Could not retrieve the VDV-KA spec's DESFire application layout (AID, file structure for
  Berechtigung vs logbook). The normative VDV-KA / KA-Chipkarte documents were not in results.
- Which DESFire generation(s) are formally certified for current VDV-KA is unconfirmed (sources
  show both SmartMX microcontrollers and DESFire in the ecosystem).

---

## Q5. How FEIG markets cVEND for these schemes / application notes

### Takeaway
FEIG explicitly markets cVEND as a single multi-application transit validator that reads open-loop
EMV/wallets and closed-loop schemes (MIFARE, CIPURSE, ITSO, VDV-KA, Calypso) "with the same
priority" and "in parallel." It is EMVCo L1/L2 and PCI PTS certified, a Visa Ready for Transit
partner, with multiple Level 2 payment kernels and SAM sockets. All claims below are vendor-reported.

### Cited Findings
- cVEND's "Multi-Application architecture supports open-loop contactless payment cards and mobile
  wallets… as well as closed-loop cards like **MIFARE, CIPURSE, ITSO, VDV-KA, or Calypso with the
  same priority**." "Closed-loop e-tickets and open-loop payment cards can be read in parallel at
  high performance." — [FEIG cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)
- The cVEND plug is "fully approved for open-loop payment by **EMVCo and PCI PTS**"; "a
  step-by-step upgrade concept enables migration from closed-loop to open-loop." — [FEIG cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)
- cVEND terminals "use **eight independent application directories** to process open loop payment
  applications **in parallel** with closed loop ticketing," and support "common RFID chips like
  Mifare, Felica, etc." — [FEIG press: multi-application technique](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/)
- Terminals are "certified according to **EMVCo Level 1 and PCI PTS 4.0**, and include **Level 2
  kernels for American Express, Discover, Mastercard and VISA**"; FEIG's transit page cites the
  multi-application architecture and **4 SAM sockets**. — [FEIG press: multi-application technique](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/); [FEIG public transport ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)
- FEIG joined the **Visa Ready for Transit** program (May 2020); the cVEND family has "certified
  kernels for VISA, American Express, Discover, Mastercard, RuPay and MADA (PURE)," with EMVCo
  Level 1 and Level 2 certification. — [FEIG Visa Ready for Transit release](https://www.FEIG.de/fileadmin/user_upload/Downloads/News/2020-06-02-VISA-Ready-for-Transit-EN.pdf)
- Product family: cVEND plug, box, box+, PIN, touch; cVEND compact II is a retrofit platform
  (integrated LTE modem/antenna, MDB interface) for app development. — [FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf); [FEIG press news](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/)

### Inferences
- FEIG's "eight independent application directories" is the marketing-level description of exactly
  the "ProxCard handler" slot mechanism the firmware exposes (VdvKa, MifareClassic, Iso, Desfire,
  Girogo, Itso, UltralightC are 7 of the closed-loop handlers; EMV is the open-loop path via the
  EmvReader/Entry Point). The handler index numbers (4–10) are consistent with a fixed table of
  directory slots. (Inference tying marketing to firmware.)
- The 4 SAM sockets provide the per-scheme secure key storage (ITSO ISAM, VDV-KA keys, Calypso/
  MIFARE keys, girogo/GeldKarte keys) needed to authenticate each closed-loop scheme. (Inference.)

### Gaps
- No FEIG-published scheme-specific application note (e.g. a dedicated "cVEND + ITSO" or
  "cVEND + VDV-KA" integration whitepaper) was located in results — only datasheets and press
  releases. FEIG's deeper integration docs appear to be behind partner/login gating.

---

## Q6. "ProxCard" handlers / multi-application reader (RFIDReaderMultiApp)

### Takeaway
A multi-application reader enables several card-scheme handlers simultaneously; on each card
presentation it runs ISO 14443 anticollision, then dispatches to the handler(s) whose scheme the
card matches, and the enabled handler performs scheme-specific selection + authentication (with SAM
keys). This is documented at the concept level by FEIG's "parallel application directories" and by
the general multi-application MIFARE problem; the specific `RFIDReaderMultiApp` class name was not
found in public sources (it is firmware-internal).

### Cited Findings
- FEIG runs "eight independent application directories to process open loop… in parallel with
  closed loop ticketing," designed to deliver "maximum possible transaction speed" at access
  barriers. — [FEIG press: multi-application technique](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/)
- General background: multi-application cards' "multi-applications feature causes problems with
  increased access times" — the latency problem that a parallel reader architecture addresses. — [NXP MIFARE4Mobile blog](https://www.nxp.com/company/about-nxp/smarter-world-blog/BL-MIFARE4MOBILE-GIVES-SMARTPHONES-MULTI-APP)
- Masabi's validator and FEIG's cVEND both describe "open-architecture" / multi-format reading
  (barcode, NFC smartcard, contactless EMV) in one device. — [Masabi Justride](https://www.masabi.com/account-based-ticketing/); [FEIG cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)

### Inferences
- "Enabling a handler" in the firmware most plausibly means: register that scheme's directory slot
  so that, after RF anticollision/SAK/ATS, the reader attempts that scheme's application SELECT and,
  on success, holds the card and runs the scheme's authentication (DESFire AES/3DES auth, ITSO ISAM
  challenge, VDV-KA MAC verification, girogo purse keys, MIFARE Classic sector-key auth). Handlers
  not enabled are skipped, reducing per-tap latency. (Inference from FEIG parallel-directory model
  + known per-scheme auth.)
- The numeric indices (VdvKa=4, MifareClassic=5, Iso=6, Desfire=7, Girogo=8, Itso=9, UltralightC=10)
  look like entries in a fixed handler-type enum; indices 0–3 (not in the enabled list) are likely
  other/base handler types (e.g. none/raw/EMV/Felica). "Iso(6)" is probably a generic ISO 14443-4
  / ISO 7816 APDU handler used as a base for the higher schemes. (Inference — not independently
  sourced.)

### Gaps
- No public documentation of FEIG's internal `RFIDReaderMultiApp` / ProxCard handler class model;
  this is firmware-internal and only inferable from the reverse-engineered symbols plus FEIG's
  marketing description of parallel directories.

---

## Q7. Account-based ticketing (ABT) and the validator backend (Masabi/Bytemark style)

### Takeaway
In ABT the fare logic lives in the cloud, not on the card: the card/phone/EMV card is just a
**token** (identifier) bound to a back-office account; the validator captures the token at tap,
sends it to the backend, and the backend computes the fare (fare capping, best-value). A validator
like Masabi's Justride reads barcodes, NFC smartcards and contactless EMV and integrates with the
cloud platform. (Masabi material is well documented; Bytemark specifics were not found in results.)

### Cited Findings
- Masabi's Justride platform "is account based and supports multiple tokens assigned to a back
  office account, so passengers no longer need to buy a ticket before traveling." — [Masabi: Everything you need to know about ABT](https://blog.masabi.com/blog/everything-you-need-to-know-about-account-based-ticketing)
- In ABT, "each form of transport medium has a back-office account assigned to it. Information is
  transmitted to this system when used at a validator or gate to make fare adjustments as needed." — [Masabi blog](https://blog.masabi.com/blog/everything-you-need-to-know-about-account-based-ticketing)
- The **Justride Validator** is a multi-format device supporting "paper and mobile barcodes,
  contactless bank cards (cEMV) and smartcards (NFC), as well as bluetooth," with an
  "open-architecture design [for] easy integration with third-party software." — [Finextra: Masabi multi-format validator](https://finextra.com/pressarticle/78732/masabi-unveils-multi-format-scanning-device-for-contactless-tap-and-ride-ticketing); [Masabi ABT](https://www.masabi.com/account-based-ticketing/)
- Deployment example: SkyBus (Australia) launched ABT with Fujitsu + Masabi, with Justride
  Validators installed fleet-wide. — [Masabi / SkyBus](https://www.masabi.com/2022/03/29/skybus-launches-new-fare-payment-system-provided-by-fujitsu-and-masabi/)

### Inferences
- A cVEND-class validator in an ABT deployment uses the EMV Entry Point only far enough to capture
  a token from the open-loop card (the PAN/token via a zero-amount or "status check" flow), then
  hands that token to the backend (Masabi/Bytemark) which does fare calculation and deferred
  authorization/settlement. This matches the Q1 inference that EMV Pre-Processing is configured for
  a zero-amount/deferred transit flow rather than a point-of-sale sale. (Inference.)
- For closed-loop schemes (ITSO/VDV-KA), the same validator can operate card-based (entitlement
  read from the chip) OR token-based (card UID/PAN used as an ABT account token) — the dual nature
  of multi-application transit readers. (Inference.)

### Gaps
- No Bytemark-specific documentation surfaced (only Masabi). Validator-to-backend API/message
  formats, token-to-account binding, and fare-calculation service internals were not found in
  public sources for either vendor.
- No source explicitly connects FEIG cVEND to Masabi/Bytemark backends (though FEIG hardware is
  commonly paired with such platforms, this was not confirmed in results).
