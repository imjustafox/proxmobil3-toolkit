# FEIG cVEND reader hardware and the OBID / ID ISC product line

The unit being reverse-engineered is the card reader inside an INIT PROXmobil3
transit validator. It identifies as "FEIG cVEND Application" firmware v02.35, model
string "cS01.05.45-49.00-2-2", `/etc/issue` = "FEIG ELECTRONIC GmbH - cVEND
Development Kit", Buildroot 2014.05 Linux. The strongest documented match is the
FEIG cVEND plug, likely the `flex`/DK configuration, a payment/validator module
marketed for transit ticket validators. Buildroot 2014.05 fits the first-generation
cVEND plug, launched October 2015, not the later cVEND plug II (PCI PTS 6.x)
generation.

## What cVEND is, and the product variants

cVEND is FEIG's family of embedded contactless payment terminals and modules
running a secure Linux OS, launched October 2015. The cVEND plug is the flush-mount
module built for transit ticket validators and fare gates, and it is the variant
most consistent with this unit. "flex" and "DK" denote developer/open-platform
configurations where the integrator writes their own Level-3 payment application
through FEIG's SDK.

Public findings:

- cVEND is a family of contactless payment terminals. Datasheets exist for plug,
  box, PIN, compact, compact LTE, touch, touch S, and extension boards
  ([FEIG datasheet index](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)).
- The first cVEND plug terminals shipped in October 2015 after about two years of
  development. The original plug was "a contactless payment terminal for public
  transport validators and ticket gates," built to meet PCI PTS
  ([FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)).
- First deployment: a bus line in the Portland-Vancouver area, about 1,100 plug
  terminals installed in validators. Riders paid with smart cards, mobile tickets,
  or credit/debit cards
  ([FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)).
- Product evolution: cVEND box for parking and vending, co-developed with plug;
  cVEND PIN, adding a stainless-steel PIN keypad for self-service and EV charging;
  cVEND touch, the newest, with flush glass PIN entry
  ([FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)).
- cVEND plug is "designed for flush integration in any kind of non-conducting front
  plates like ticket validators." The module "disappears almost completely in the
  validator and only the 28.5 mm large, round contactless symbol remains visible"
  ([FEIG public transport page](https://www.feig.de/en/public-transport/)).
- cVEND plug flex is "built for system integrators who want to develop their own
  Level 3 payment application, with an optional SDK." It runs "a secure Linux-based
  operating system"
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- cVEND plug flex dimensions: 79 x 70 x 31.1 mm (W x H x D), visible diameter
  28.5 mm
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- cVEND plug II is the PCI PTS 6.x-certified successor to the first-generation
  plug, about 80 x 70 x 31.1 mm
  ([FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/);
  [FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)).
- Software configurations named for the plug: "alpha, DK, PayServ.GWS, L2,
  generic." The page does not explain the numbering
  ([FEIG cVEND plug product page](https://www.feig.de/en/payment-terminals/cvend-plug/)).

Inference: `/etc/issue` saying "cVEND Development Kit," the flex/DK
configuration, and the device identifying as a "cVEND Application" strongly
indicate the unit is a cVEND plug in the flex/DK open app-development
configuration. INIT, the integrator, wrote the application layer on FEIG's secure
Linux platform.

Buildroot 2014.05 aligns with the first-generation (Gen I) cVEND plug timeframe,
not the later Gen II / plug II (PCI 6.x). Gen I had 128 MB RAM and 256 MB flash;
Gen II has 512 MB and 1 GB. The generation could be confirmed by checking RAM and
flash size.

Gap: no single "cVEND plug" base datasheet was machine-readable. FEIG datasheets
are FlateDecode-compressed PDFs that WebFetch could not extract, and feig.de PDFs
returned 403 on retry. Specs here come from FEIG HTML product pages, which describe
the current plug II generation.

## The model string and FEIG versioning

Not documented publicly. The reader reports firmware/app version 02.35 separately
("cVEND Application" v02.35). The "cS01.05.45-49.00-2-2" string is almost certainly
a FEIG internal hardware/platform-build identifier. Its exact field meaning could
not be sourced. FEIG's OBID RFID readers conventionally use dotted `xx.yy.zz`
firmware versions (for example 02.00.00), consistent with the "02.35" app version
here.

Findings:

- FEIG OBID readers use dotted firmware versions. OBID classic-pro and ISC.MRU102
  manuals reference firmware "02.00.00" as a baseline
  ([FEIG OBID manual summary](https://manualmachine.com/feigelectronic/obidclassicproidcpr0320cd/21524749-user-manual)).
- FEIG's C++ FEDM host library uses dotted x.y.z version numbers (library, not
  reader firmware)
  ([FEDM manual](https://community.st.com/ysqtg83639/attachments/ysqtg83639/st25-nfc-rfid-tags-readers-forum/6729/1/C++%20FEDM%20-%20H10202-32e-ID-B.pdf)).

Inference: "cS" plausibly abbreviates cVEND System or Software. The leading field
"cS01.05.45" likely encodes a platform, hardware, or OS build identifier, and
"49.00-2-2" a sub-revision or variant. This is pattern-matching, not documented.
The user-visible "02.35" is the application/firmware release version, in FEIG's
`xx.yy` style, and is distinct from the long model/platform string.

Gaps: no public FEIG document decodes the "cS..." format. Decoding would require
the NDA cVEND SDK/integration docs or FEIG support (`obid-support@feig.de` /
`info@feig.de`). It is also unconfirmed whether "02.35" is the FEIG platform
firmware or INIT's application build.

## Relation to OBID / ID ISC

cVEND and OBID/ID ISC are both FEIG 13.56 MHz RFID product lines. cVEND leverages
FEIG's RFID heritage, but no public document proves a shared firmware codebase.
They are architecturally distinct. OBID/ID ISC are host-protocol RFID readers
(FEDM/ISO host commands). cVEND is a full Linux-based payment terminal with an
onboard contactless front end and EMV payment kernels.

Findings:

- FEIG "was already known for high-quality RFID products." The cVEND plug was
  designed to read closed-loop cards as well as process open-loop bank-card
  payments ([FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)).
- The OBID/ID ISC family includes ID ISC.MR101/102 (mid-range), ID ISC.PR/PRH101
  (proximity), ID ISC.LR (long-range), ID ISC.MRU102 (UHF), and OBID classic-pro ID
  CPR (for example CPR.03.20 and CPR40)
  ([FEIG OBID manuals](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- OBID readers are integrated as RFID encoders in third-party systems, such as the
  Oracle Hospitality "FEIG OBID RFID Encoder"
  ([Oracle docs](https://docs.oracle.com/en/industries/hospitality/cruise/property_management/20.3/dvice/c_feig_obid_rfid_encoder.htm)).

Inference: cVEND's contactless stack and OBID readers likely share FEIG RF/analog
front-end IP and ISO14443/15693 protocol know-how. But cVEND runs a
payment-oriented Linux application stack, not OBID host-command firmware. Treat
that as informed inference, not documented fact.

Gap: no public source traces cVEND firmware to the ISC/CPR firmware lines or names
a shared RF driver or chip across both families.

## Contactless standards and the RF transceiver

cVEND plug supports ISO/IEC 14443 Type A and B, ISO/IEC 15693, NFC card emulation,
and MIFARE. Sibling cVEND models additionally list Sony FeliCa and Calypso. Transit
closed-loop schemes (MIFARE, CIPURSE, ITSO, VDV-KA, Calypso) are handled through the
multi-application architecture and SAM extension board. The specific RF transceiver
IC is not publicly documented for cVEND.

Findings:

- cVEND plug and plug flex contactless interface: "ISO/IEC 14443-A/-B payment
  cards, NFC mobile devices in card emulation mode, MIFARE, ISO 15693, and other
  contactless cards"
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/);
  [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)).
- Level-2 EMV payment kernels: VISA, Mastercard, American Express, Discover, JCB,
  RuPay, UnionPay, PURE. PCI PTS 5.x and EMVCo L1 certified for Gen I, PCI PTS 6.x
  for plug II
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- Closed-loop and transit support for cVEND plug: "MIFARE, CIPURSE, ITSO, VDV-KA,
  or Calypso with the same priority" in the multi-application architecture
  ([FEIG cVEND plug NMI datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_NMI_EN.pdf)).
- SAM Extension Board (4 SAM sockets) "developed for public transport," supporting
  VDV-KA, ITSO, CIPURSE, and MIFARE
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- Sony FeliCa is named explicitly on sibling products. cVEND box II lists
  "ISO/IEC 14443-A/-B, ISO/IEC 15693, ... MIFARE, Calypso, Sony FeliCa and other"
  ([FEIG cVEND box II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet_cVEND-box-II-Solutions-with-payment-app-from-FEIG.pdf)).
- FEIG public-transport messaging references a "transparent channel" for ISO14443
  chip cards in FEIG payment applications, giving raw card APDU access to the
  integrator's app
  ([FEIG public transport and ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)).
- FCC filings confirm cVEND plug operates at 13.56 MHz with an integrated antenna,
  classified as an "RFID Reader," external power 5.0 V DC
  ([FCC ID PJMCVEND](https://fcc.report/FCC-ID/PJMCVEND/2598130.pdf)).
- Context, not cVEND-specific: common NXP 13.56 MHz reader ICs covering
  ISO14443, ISO15693, MIFARE, and NFC include CLRC663 (CLRC66301) and the
  PN512/PN7xxx families
  ([DigiKey NXP CLRC66301 listing](https://www.digikey.fr/en/products/detail/nxp-usa-inc/CLRC66301HN-551/3430663)).

Inference: MIFARE support is confirmed generically. DESFire, Ultralight /
Ultralight-C, and NTAG are all ISO14443-A types and are almost certainly
reachable. DESFire is the dominant transit credential, and the PROXmobil3 context
implies MIFARE handling, but FEIG's public pages name only "MIFARE" generally.
Specific subtype support is inferred, not documented.

The cVEND RF front end is plausibly an NXP CLRC663-class multiprotocol reader IC,
which fits ISO14443A/B, ISO15693, FeliCa, and NFC plus FEIG's OBID heritage. That
is an inference. No teardown or FCC internal-photo confirmation was obtained.

Gaps: no primary source names the exact RF transceiver IC or antenna driver, or
whether FeliCa, DESFire, and Ultralight are explicitly supported on the cVEND plug
versus the box. FCC internal-photo PDFs, which would reveal the RF chip, could not
be fetched; fcc.report and feig.de returned HTTP 403 to WebFetch. Manual retrieval
of FCC ID PJMCVEND, PJMCVNDA internal photos, and schematic or block-diagram
exhibits is the next step.

## Physical and electrical

cVEND plug is a roughly 79 x 70 x 31 mm module, powered at 5.0-5.5 V DC, with a
secure ARM9 CPU, Ethernet / RS232 (V.24) / RS232-LVTTL / USB 2.0 interfaces, four
SAM sockets (ID-000, through the extension board), six LEDs, and a multi-frequency
buzzer. Serial, both RS232 and low-voltage TTL, is present, which is relevant for
the RE console and UART. The two hardware generations differ mainly in memory size.

Findings:

- Dimensions: 79 x 70 x 31.1 mm (W x H x D), visible contactless symbol diameter
  28.5 mm
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- Power: 5.0-5.5 V DC, under 1 A in operation excluding peripherals, under 1 mA
  standby. Wake-up by digital input or timer
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/);
  [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)).
- Peripheral interfaces: Ethernet, RS232 (V.24), RS232-LVTTL, USB 2.0 Device/OTG,
  MDB through the Vending Extension Board
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/);
  [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)).
- Online connection: Ethernet and IP-over-USB, optional LTE
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- CPU and security: secure ARM9 CPU, real-time memory encryption, crypto hardware
  acceleration, TRNG, tamper-proof hardware, side-channel attack protection
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- Memory: Gen I (plug flex) 128 MB RAM and 256 MB flash; Gen II (plug II) 512 MB
  RAM and 1 GB flash
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/);
  [FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)).
- SAM: four SAM sockets, ID-000 format, through the optional SAM Extension Board.
  microSD (SDIO/SD v2.0) is also on the extension board
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- LEDs and buzzer: six LEDs (4 green, 1 red, 1 yellow), internal multi-frequency
  buzzer, illuminated contactless logo
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
- RTC and battery: battery-backed RTC, 3 V lithium 540 mAh, rated 15 years at
  25 C (plug II)
  ([FEIG cVEND plug page](https://www.feig.de/en/payment-terminals/cvend-plug/)).
- Environment: operating -30 C to +70 C, storage -30 C to +80 C, 5-95% humidity,
  condensing, with a moisture-resistant coating
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).

Inference: the unit's serial console almost certainly rides on the RS232-LVTTL
low-voltage TTL UART pins rather than the V.24/RS232-level port, which is standard
for embedded Linux debug consoles. The four SAM sockets are the SAV/SAM slots to
look for. In a transit install they hold the scheme keys (VDV-KA, ITSO, CIPURSE,
Calypso).

Gap: the exact serial pinout and connector pin assignment are not on the public
pages; they are in the NDA integration manual. No public teardown giving the RF IC
or connector pinout was found.

## Transit validator positioning

FEIG markets cVEND plug as the module inside public-transport ticket validators and
fare gates, with a dedicated public-transport and ticketing product line and a
multi-application technique covering open-loop and closed-loop transactions.

Findings:

- FEIG's page "Cashless payment systems for public transport and transit" markets
  cVEND for validators and ticketing
  ([FEIG public transport and ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)).
- cVEND plug "is electrically and mechanically designed for transit applications
  and complies with transit specifications of global card brands as well as with
  railway and automotive standards"
  ([FEIG cVEND plug datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_TOPP_EN.pdf)).
- FEIG press release: "FEIG's multi-application technique gives a boost to
  transaction speed of mass transit systems." Title and existence confirmed through
  search; the article body was not retrieved
  ([FEIG press/news](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/)).
- The 10th-anniversary brief "10 Jahre cVEND" (PDF, dated 2025-10-23) and the
  English "10 years of cVEND" page document the transit origin and the
  Portland-Vancouver bus deployment of about 1,100 validators
  ([FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/);
  [FEIG 10-Jahre-cVEND PDF](https://www.feig.de/wp-content/uploads/2025-10-23-10-Jahre-cVEND.pdf)).
- Railway Gazette covered FEIG transit contactless in "Tickets with a flick of the
  wrist"
  ([Railway Gazette](https://railwaygazette.com/technology/tickets-with-a-flick-of-the-wrist/41303.article)).

Inference: the INIT PROXmobil3 use case (cVEND plug embedded in a transit
validator, with an integrator-written app on FEIG's secure Linux) matches FEIG's
documented reference architecture for cVEND plug in validators.

Gap: no FEIG document specifically naming the INIT PROXmobil3 or INIT as an
integration partner was found in public search.

## Sources

- FEIG cVEND plug flex product page, the richest spec source:
  https://www.feig.de/en/payment-terminals/cvend-plug-flex/
- FEIG cVEND plug (plug II) product page:
  https://www.feig.de/en/payment-terminals/cvend-plug/
- FEIG "10 years of cVEND": https://www.feig.de/en/news-en/10-years-of-cvend/
- FEIG public transport and ticketing:
  https://www.feig.de/en/industries/public-transport-ticketing/
- FEIG datasheet PDFs (FlateDecode-compressed, not text-extractable through
  WebFetch; feig.de PDF URLs return 403 on direct fetch):
  `Data_sheet_cVEND_plug_flex_EN.pdf`, `Data_sheet_cVEND_plug_NMI_EN.pdf`,
  `Data_sheet_cVEND_plug_TOPP_EN.pdf`, `Data_sheet_cVEND_SAM_Extension_Board_EN.pdf`,
  `Data_sheet_cVEND_Vending_Extension_Board_EN.pdf`
- FCC IDs (FEIG ELECTRONIC GmbH): PJMCVEND (cVEND plug), PJMCVNDA, PJMCVNDB (cVEND
  plug, modular approval 2023-08-15), PJMCVPIN (cVEND PIN, test report 2022-06-17),
  via fcc.report (directory pages return 403 to WebFetch; use a browser for
  internal photos)
- FEIG OBID/ID ISC manuals for lineage context: ManualsLib / ManualMachine, Oracle
  Hospitality OBID RFID Encoder docs

## Method and reliability

FEIG's HTML product pages describe the current product, largely the Gen II plug.
Where Gen I and Gen II differ (memory, PCI version), both are noted. The unit is
likely Gen I because of Buildroot 2014.05.

All device-spec numbers above come from FEIG HTML pages. FEIG datasheet PDFs and
FCC internal-photo exhibits could not be parsed by the tooling (compressed PDFs,
HTTP 403), so the exact RF IC, serial pinout, and subtype card support
(DESFire/Ultralight/NTAG) remain gaps. They need a manual PDF/FCC pull or FEIG NDA
docs.
