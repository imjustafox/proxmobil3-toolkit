# FEIG ELECTRONIC cVEND Reader Hardware and FEIG OBID / ID ISC Product Lineage

> Scope note: The unit being reverse-engineered is the card reader inside an INIT PROXmobil3 transit
> validator. It identifies as "FEIG cVEND Application" firmware v02.35, model string
> "cS01.05.45-49.00-2-2", `/etc/issue` = "FEIG ELECTRONIC GmbH - cVEND Development Kit",
> Buildroot 2014.05 Linux. The strongest documented match is the **FEIG cVEND plug** (likely the
> `flex`/DK configuration), a payment/validator module explicitly marketed for transit ticket
> validators. Buildroot 2014.05 is consistent with the first-generation cVEND plug (launched Oct 2015),
> NOT the later "cVEND plug II" (PCI PTS 6.x) generation.

## What is the FEIG cVEND product, and the cVEND variants (plug / flex / box / PIN / compact / touch)?

### Takeaway
cVEND is FEIG's family of embedded contactless payment terminals/modules running a secure Linux OS,
launched October 2015. The **cVEND plug** is the flush-mount module purpose-built for transit ticket
validators and fare gates, and is the variant most consistent with the reverse-engineered unit. "flex"
(and "DK") denote developer/open-platform configurations where the integrator writes their own Level-3
payment application via FEIG's SDK.

### Cited Findings
- cVEND is a family of contactless payment terminals; datasheets exist for plug, box, PIN, compact, compact LTE, touch, touch S, and extension boards — [FEIG datasheet index via search](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)
- First cVEND plug terminals shipped **October 2015** after ~2 years of development; the original cVEND plug was "a contactless payment terminal for public transport validators and ticket gates," built to meet PCI PTS — [FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)
- First deployment: a bus line in the Portland–Vancouver area, ~1,100 plug terminals installed in validators; riders pay with smart cards, mobile tickets, or credit/debit cards — [FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)
- Product-line evolution: cVEND **box** (parking/vending, co-developed with plug), cVEND **PIN** (adds stainless-steel PIN keypad for self-service/EV charging), cVEND **touch** (newest; flush glass PIN entry) — [FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)
- cVEND **plug** = "designed for flush integration in any kind of non-conducting front plates like ticket validators"; the module "disappears almost completely in the validator and only the 28.5 mm large, round contactless symbol remains visible" — [FEIG public transport page via search](https://www.feig.de/en/public-transport/)
- cVEND **plug flex** is "built for system integrators who want to develop their own Level 3 payment application, with an optional SDK"; runs "a secure Linux-based operating system" — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- cVEND **plug flex** dimensions: 79 mm × 70 mm × 31.1 mm (W×H×D), visible Ø 28.5 mm — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- "cVEND plug II" is the PCI PTS 6.x-certified successor to the first-generation cVEND plug; ~80×70×31.1 mm — [FEIG cVEND plug page via search](https://www.feig.de/en/payment-terminals/cvend-plug/); [FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)
- Software configurations named for the plug: "alpha, DK, PayServ.GWS, L2, generic" (the page does not explain the numbering) — [FEIG cVEND plug product page](https://www.feig.de/en/payment-terminals/cvend-plug/)

### Inferences
- The `/etc/issue` "cVEND Development Kit" + the flex/DK ("DK" = Development Kit) configuration + the device self-identifying as a "cVEND Application" strongly indicate the RE unit is a **cVEND plug in the flex/DK (open app-development) configuration**, i.e. the integrator (INIT) wrote the application layer on FEIG's secure-Linux platform.
- Buildroot 2014.05 aligns with the **first-generation (Gen I) cVEND plug** timeframe (launched Oct 2015), not the later Gen II / plug II (PCI 6.x). Gen I had 128 MB RAM / 256 MB flash; Gen II has 512 MB RAM / 1 GB flash (see electrical section) — the RE unit's generation could be confirmed by checking its RAM/flash size.

### Gaps
- No single "cVEND plug" base datasheet text was machine-readable (FEIG datasheets are FlateDecode-compressed PDFs that WebFetch could not extract; feig.de PDFs returned 403 on retry). Specs here come from FEIG HTML product pages, which describe the current plug II generation.

## What does the model/firmware string "cS01.05.45-49.00-2-2" encode? How does FEIG version readers?

### Takeaway
Not documented publicly. The reader reports firmware/app version **02.35** separately ("cVEND
Application" v02.35). The "cS01.05.45-49.00-2-2" string is almost certainly a FEIG internal
hardware/platform-build identifier; its exact field meaning could not be sourced. FEIG's OBID RFID
readers conventionally use dotted `xx.yy.zz` firmware versions (e.g. 02.00.00), consistent with the
"02.35" app version seen on this unit.

### Cited Findings
- FEIG OBID readers use dotted firmware versions, e.g. OBID classic-pro and ISC.MRU102 manuals reference firmware "02.00.00" as a baseline — [search summary of FEIG OBID manuals](https://manualmachine.com/feigelectronic/obidclassicproidcpr0320cd/21524749-user-manual)
- FEIG's C++ FEDM host library uses dotted x.y.z version numbers (library, not reader firmware) — [search summary, FEDM manual](https://community.st.com/ysqtg83639/attachments/ysqtg83639/st25-nfc-rfid-tags-readers-forum/6729/1/C++%20FEDM%20-%20H10202-32e-ID-B.pdf)

### Inferences
- "cS" plausibly abbreviates **cVEND System/Software**; the leading field "cS01.05.45" likely encodes a platform/hardware or OS build identifier and "49.00-2-2" a sub-revision/variant — this is unverified pattern-matching, NOT documented.
- The user-visible **"02.35"** is the application/firmware release version (matches FEIG's `xx.yy` style); it is a distinct value from the long model/platform string.

### Gaps
- No public FEIG document decodes the "cS..." string format. Decoding would require FEIG cVEND SDK/integration docs (NDA-gated) or FEIG support (obid-support@feig.de / info@feig.de).
- Could not confirm whether "02.35" is the FEIG platform firmware or INIT's application build.

## How does cVEND relate to the FEIG OBID / ID ISC reader families? Shared chipset/firmware lineage?

### Takeaway
cVEND and OBID/ID ISC are both FEIG 13.56 MHz RFID product lines, and cVEND explicitly leverages FEIG's
RFID heritage, but no public document proves a shared firmware codebase. They are architecturally
distinct: OBID/ID ISC are host-protocol RFID readers (FEDM/ISO host commands); cVEND is a full
Linux-based payment terminal with an onboard contactless front end plus EMV payment kernels.

### Cited Findings
- FEIG "was already known for high-quality RFID products"; the cVEND plug was designed to read closed-loop cards as well as process open-loop bank-card payments — [FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)
- FEIG's OBID / ID ISC family includes ID ISC.MR101/102 (mid-range), ID ISC.PR/PRH101 (proximity), ID ISC.LR (long-range), ID ISC.MRU102 (UHF), and OBID classic-pro ID CPR (e.g. CPR.03.20, CPR40) — [FEIG OBID manuals via ManualsLib/ManualMachine](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- OBID readers are integrated as RFID encoders in third-party systems (e.g. Oracle Hospitality "FEIG OBID RFID Encoder") — [Oracle docs](https://docs.oracle.com/en/industries/hospitality/cruise/property_management/20.3/dvice/c_feig_obid_rfid_encoder.htm)

### Inferences
- cVEND's contactless stack and OBID readers almost certainly share FEIG RF/analog front-end IP and ISO14443/15693 protocol know-how (common engineering heritage), but the cVEND runs a payment-oriented Linux application stack rather than the OBID host-command firmware — treat as informed inference, not documented fact.

### Gaps
- No public source traces cVEND firmware to the ISC/CPR firmware lines, or names a shared RF driver/chip across both families.

## Supported contactless standards and the RF/transceiver IC

### Takeaway
cVEND plug supports ISO/IEC 14443 Type A and B, ISO/IEC 15693, NFC card-emulation, and MIFARE; sibling
cVEND models additionally list Sony FeliCa and Calypso. Transit closed-loop schemes (MIFARE, CIPURSE,
ITSO, VDV-KA, Calypso) are handled via the multi-application architecture / SAM extension board. The
specific RF transceiver IC is NOT publicly documented for cVEND.

### Cited Findings
- cVEND plug/plug flex contactless interface: "ISO/IEC 14443-A/-B payment cards, NFC mobile devices in card emulation mode, MIFARE, ISO 15693, and other contactless cards" — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/); [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)
- Level-2 EMV payment kernels: VISA, Mastercard, American Express, Discover, JCB, RuPay, UnionPay, PURE; PCI PTS 5.x + EMVCo L1 certified (Gen I), PCI PTS 6.x (plug II) — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- Closed-loop/transit support list for cVEND plug: "MIFARE, CIPURSE, ITSO, VDV-KA, or Calypso with the same priority" in the multi-application architecture — [FEIG cVEND plug NMI datasheet via search](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_NMI_EN.pdf)
- SAM Extension Board (4 SAM sockets) "developed for public transport," supports VDV-KA, ITSO, CIPURSE, MIFARE — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- Sony FeliCa named explicitly on sibling products: cVEND box II contactless interface = "ISO/IEC 14443-A/-B, ISO/IEC 15693, ... MIFARE, Calypso, Sony FeliCa and other" — [FEIG cVEND box II datasheet via search](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet_cVEND-box-II-Solutions-with-payment-app-from-FEIG.pdf)
- FEIG public-transport messaging references a "transparent channel" for ISO14443 chip cards in FEIG payment applications (raw card APDU access to the integrator's app) — [FEIG public transport/ticketing page via search](https://www.feig.de/en/industries/public-transport-ticketing/)
- FCC filings confirm cVEND plug operates at **13.56 MHz** with an **integrated antenna**, classified as an "RFID Reader," external power 5.0 V DC — [search summary of FCC IDs PJMCVEND / PJMCVNDA / PJMCVNDB](https://fcc.report/FCC-ID/PJMCVEND/2598130.pdf)
- (Context, not cVEND-specific) Common NXP 13.56 MHz reader ICs covering ISO14443+ISO15693+MIFARE+NFC include CLRC663 (CLRC66301) and PN512/PN7xxx families — [DigiKey NXP CLRC66301 listing](https://www.digikey.fr/en/products/detail/nxp-usa-inc/CLRC66301HN-551/3430663)

### Inferences
- MIFARE family support is confirmed generically; **DESFire**, **Ultralight / Ultralight-C**, and **NTAG** are all ISO14443-A types and are almost certainly reachable (DESFire is the dominant transit credential and the PROXmobil3 context implies MIFARE handling), but FEIG's public pages name only "MIFARE" generally — specific sub-type support is **inferred, not documented**.
- The cVEND RF front end is plausibly an NXP CLRC663-class multiprotocol reader IC (fits ISO14443A/B + ISO15693 + FeliCa + NFC and FEIG's own OBID heritage), but this is an inference; no teardown/FCC-internal-photo confirmation was obtained.

### Gaps
- No primary source names the exact RF transceiver IC, antenna driver, or whether FeliCa/DESFire/Ultralight are explicitly supported on the cVEND **plug** (vs. box). FCC internal-photo PDFs (which would reveal the RF chip) could not be fetched — fcc.report and feig.de returned HTTP 403 to WebFetch. Recommend manual retrieval of FCC ID PJMCVEND / PJMCVNDA internal photos and schematic/block-diagram exhibits.

## Physical / electrical: power, interfaces, SAM slots, LEDs, buzzer, CPU

### Takeaway
cVEND plug is a ~79×70×31 mm module, 5.0–5.5 V DC powered, with a secure ARM9 CPU, Ethernet / RS232
(V.24) / RS232-LVTTL / USB 2.0 interfaces, 4 SAM sockets (ID-000, via extension board), 6 LEDs, and a
multi-frequency buzzer. Serial (RS232 and low-voltage TTL serial) is present — relevant for the RE
console/UART. Two hardware generations differ mainly in memory size.

### Cited Findings
- **Dimensions:** 79 × 70 × 31.1 mm (W×H×D); visible contactless symbol Ø 28.5 mm — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- **Power:** 5.0–5.5 V DC; <1 A in operation (peripherals excluded), <1 mA standby; wake-up by digital input or timer — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/); [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)
- **Peripheral interfaces:** Ethernet, RS232 (V.24), RS232-LVTTL, USB 2.0 Device/OTG, MDB (via Vending Extension Board) — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/); [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)
- **Online connection:** Ethernet and IP-over-USB; optional LTE — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- **CPU / security:** Secure ARM9 CPU, real-time memory encryption, crypto HW acceleration, TRNG, tamper-proof hardware, side-channel attack protection — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- **Memory:** Gen I (plug flex) 128 MB RAM / 256 MB flash; Gen II (plug II) 512 MB RAM / 1 GB flash — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/); [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)
- **SAM:** 4 SAM sockets, ID-000 format, via optional SAM Extension Board; microSD (SDIO/SD v2.0) also via extension board — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- **LEDs / buzzer:** 6 LEDs (4 green, 1 red, 1 yellow), internal multi-frequency buzzer, illuminated contactless logo — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)
- **RTC / battery:** battery-backed RTC; 3 V lithium 540 mAh, rated 15 years at 25 °C (plug II) — [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)
- **Environment:** operating −30 °C to +70 °C; storage −30 °C to +80 °C; 5–95% humidity, condensing (moisture-resistant coating) — [FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)

### Inferences
- The RE unit's serial console almost certainly rides on the **RS232-LVTTL** (low-voltage TTL UART) pins rather than the V.24/RS232-level port — standard for embedded Linux debug consoles.
- 4 SAM sockets (ID-000 SIM-style) are the SAV/SAM slots to look for; in a transit install these hold the transit scheme keys (VDV-KA/ITSO/CIPURSE/Calypso).

### Gaps
- Exact serial pinout / connector pin assignment is not on the public pages (it is in the NDA integration manual). No public teardown giving the RF IC or connector pinout was found.

## FEIG application notes / product briefs describing cVEND as a transit validator

### Takeaway
FEIG explicitly and repeatedly markets cVEND plug as the module inside public-transport ticket
validators and fare gates, with a dedicated public-transport/ticketing product line and multi-application
(open-loop + closed-loop) transaction technique.

### Cited Findings
- FEIG dedicated page "Cashless payment systems for public transport and transit" markets cVEND for validators/ticketing — [FEIG public transport & ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)
- cVEND plug "is electrically and mechanically designed for transit applications and complies with transit specifications of global card brands as well as with railway and automotive standards" — [FEIG cVEND plug datasheet via search](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_TOPP_EN.pdf)
- FEIG press release "FEIG's multi-application technique gives a boost to transaction speed of mass transit systems" — [FEIG press/news](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/) (title/existence confirmed via search; article body not retrieved)
- 10th-anniversary brief "10 Jahre cVEND" (PDF, dated 2025-10-23) and the English "10 years of cVEND" page document the transit origin and Portland–Vancouver bus deployment (~1,100 validators) — [FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/); [FEIG 10-Jahre-cVEND PDF via search](https://www.feig.de/wp-content/uploads/2025-10-23-10-Jahre-cVEND.pdf)
- Railway Gazette covered FEIG transit contactless ("Tickets with a flick of the wrist") — [Railway Gazette via search](https://railwaygazette.com/technology/tickets-with-a-flick-of-the-wrist/41303.article)

### Inferences
- The INIT PROXmobil3 use case (cVEND plug embedded in a transit validator, integrator-written app on FEIG's secure Linux) matches FEIG's documented reference architecture for cVEND plug in validators exactly.

### Gaps
- No FEIG document specifically naming the INIT PROXmobil3 or INIT as an integration partner was found in public search.

---
## Source summary (primary FEIG where possible)
- FEIG cVEND plug flex product page (HTML, richest spec source): https://www.feig.de/en/payment-terminals/cvend-plug-flex/
- FEIG cVEND plug (plug II) product page: https://www.feig.de/en/payment-terminals/cvend-plug/
- FEIG "10 years of cVEND" history: https://www.feig.de/en/news-en/10-years-of-cvend/
- FEIG public transport & ticketing: https://www.feig.de/en/industries/public-transport-ticketing/
- FEIG datasheet PDFs (FlateDecode-compressed, not text-extractable via WebFetch; feig.de PDF URLs 403 on direct fetch): e.g. Data_sheet_cVEND_plug_flex_EN.pdf, Data_sheet_cVEND_plug_NMI_EN.pdf, Data_sheet_cVEND_plug_TOPP_EN.pdf, Data_sheet_cVEND_SAM_Extension_Board_EN.pdf, Data_sheet_cVEND_Vending_Extension_Board_EN.pdf
- FCC IDs (FEIG ELECTRONIC GmbH): PJMCVEND (cVEND plug), PJMCVNDA, PJMCVNDB (cVEND plug, modular approval 2023-08-15), PJMCVPIN (cVEND PIN, test report 2022-06-17) — via fcc.report (directory pages 403 to WebFetch; use browser for internal photos)
- FEIG OBID/ID ISC manuals (lineage context): ManualsLib / ManualMachine, Oracle Hospitality OBID RFID Encoder docs

## Notes on method / reliability
- FEIG's HTML product pages describe the CURRENT product (largely the Gen II plug); where Gen I vs Gen II differs (memory, PCI version), both are noted. The RE unit is likely Gen I (Buildroot 2014.05).
- All device-spec numbers above are from FEIG HTML pages. FEIG datasheet PDFs and FCC internal-photo exhibits could not be parsed by the tooling (compressed PDFs / HTTP 403), so the exact RF IC, serial pinout, and sub-type card support (DESFire/Ultralight/NTAG) remain documented gaps requiring a manual PDF/FCC pull or FEIG NDA docs.
