# FEIG cVEND transit and payment application stack

This covers the fare-media and payment schemes a FEIG cVEND validator handles
(EMVCo contactless, ITSO, Girogo, VDV-KA, account-based ticketing), mapped against
the reverse-engineered cVEND firmware 02.35. The enabled "ProxCard" handlers are
VdvKa(4), MifareClassic(5), Iso(6), Desfire(7), Girogo(8), Itso(9), UltralightC(10),
plus `emvco_ep_configure`/`emvco_ep_preprocess` and an `EmvReader`.

Sourcing note: FEIG's product claims are vendor-reported marketing. The EMVCo Book
A/B normative text was not retrievable in full because the spec PDFs sit behind
emvco.com document search. Entry-point mechanics below come from patent filings
that cite Book A tables, plus secondary summaries, and are flagged accordingly.

## EMVCo Level 2 Entry Point

The firmware symbols `emvco_ep_configure` and `emvco_ep_preprocess` correspond
directly to the EMVCo Book B Entry Point: the terminal-side state machine that
polls for a contactless card, runs Pre-Processing (the Entry Point sub-process that
evaluates the transaction amount against per-scheme limits), performs Combination
Selection (matching the card's AID and Kernel ID to a configured reader
combination), and activates the matching Level 2 kernel. The Entry Point cannot run
without configuration data. Each supported card brand must be provisioned as a
reader combination with its AID, Kernel ID, and transaction limits. That is why an
EMV-capable reader will not start EMV polling until a config object exists. The
concept is documented; the exact Book B wording was not retrieved.

Findings:

- EMVCo's Entry Point Specification is "an interoperable terminal specification
  that lets a single terminal process contactless payments regardless of the
  payment application the card supports."
- The Kernel ID is defined in Book B and "defines a one-to-one matching between the
  card application and the contactless kernel in the reader"
  ([EMVCo Kernel ID page](https://www.emvco.com/processes-category/kernel-id/)).
- Entry Point Pre-Processing sets indicators "per reader Combination (AID-Kernel
  ID) as defined in Book A, Table 5-3," and those indicators are passed to the
  selected kernel
  ([US Patent 11107055](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11107055)).
- Each reader Combination may have a set of Entry Point Configuration Data, as
  defined in Table 5-2 of Book A, and "all elements defined in this table are
  optional"
  ([US Patent 11138583](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11138583)).
- A contactless transaction "may begin at Start A or Start B depending on whether
  the transaction amount is variable or not." Pre-processing is the start for
  variable-amount transactions; fixed-amount transactions can begin later and skip
  pre-processing
  ([US Patent 11138583](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11138583)).
- The EMV kernel is "the software that point-of-sale terminals and ATMs use to
  process contactless transactions." A kernel "can co-exist with [other] kernels in
  existing payment acceptance terminals and readers"
  ([EMVCo knowledge hub](https://www.emvco.com/knowledge-hub/4-key-features-of-the-new-emv-contactless-kernel-specification/)).
- Pre-Processing evaluates the amount against per-combination limits such as the
  Contactless Transaction Limit, CVM Required Limit, and Floor Limit. Above the CVM
  limit, cardholder verification (PIN, signature, biometric, or CDCVM) is required.
  Below the floor limit, the transaction can be accepted without going online
  ([Wikipedia: Contactless payment](https://en.wikipedia.org/wiki/Contactless_payment)).
- Transit terminals may use non-standard polling sequences, for example a Type A
  signal followed by two Type B signals. They are advised to handle card clash by
  disabling UID-clash logic or lowering polling speed
  ([US Patent 11734669](https://patents.google.com/patent/US11734669);
  [Google Wallet open-loop transit requirements](https://developers.google.com/wallet/tickets/open-loop/technical-integration/basic-requirements)).

Inference: `emvco_ep_configure` is almost certainly the routine that loads and
validates the Entry Point Configuration Data, the set of reader combinations with
AID, Kernel ID, and limits per brand. If no valid combination set is configured,
the Entry Point has nothing to match a card against, which explains why EMV polling
will not start without a config. `emvco_ep_preprocess` maps to Book B
Pre-Processing: it runs the per-combination amount checks and sets indicators such
as status check requested, zero amount, CVM required, and online required before
the card is even selected. That is consistent with the Start A / Start B split.

For open-loop transit, the amount at tap is typically zero or a nominal tap amount,
with fare computed later by the back office. The reader is therefore likely
configured so Pre-Processing treats it as a zero-amount or deferred-authorization
flow rather than a fixed retail sale. That is an inference, not directly confirmed
in the retrieved sources. The `EmvReader` symbol is likely the firmware wrapper
that owns the Entry Point and one or more Level 2 kernels, parallel to the
ProxCard handlers that own the closed-loop schemes.

Gaps: EMV Book B and Book A normative text could not be retrieved directly;
emvco.com gates the PDFs behind document search. Table 5-2 and 5-3 contents are
known only through patent paraphrase. No source explicitly ties the FEIG firmware
function names to EMVCo nomenclature. The mapping is inference based on the exact
entry point and pre-process terminology.

## ITSO

ITSO is the UK's national technical specification for interoperable smart
ticketing. The ticketing application is the ITSO Shell on customer media (smartcard
or phone). Products and entitlements are IPEs. Security is enforced by an ISAM, and
the back office is the HOPS (Host Operator or Processing System). Part 10 maps the
logical Shell onto physical card platforms, including DESFire; DESFire support and
placeholders are in the current Part 10 revision.

Findings:

- ITSO Specification Version 2.1.5 is "a UK technical platform for interoperable
  smart ticketing... defines the interfaces needed for smart media, terminals, back
  offices, and separate ticketing systems to work together"
  ([ITSO technical specification](https://www.itso.org.uk/itso-specification/itso-technical-specification)).
- The ITSO Shell is the application on the card (Part 2). The three-layer model
  separates the customer's card or device, the Shell, and the product stored within
  it.
- IPEs (ITSO Product Entities) are the core product concept (Part 1). Part 5
  specifies standard IPEs such as period passes and entitlement products, with
  value records and transaction logs.
- The ISAM (ITSO Secure Application Module) runs within terminals and back-office
  systems and, with the ISMS, "protect[s] every transaction through encryption and
  authentication" (Parts 7/8).
- HOPS (Host Operator or Processing System) is the ITSO back office. It "processes
  transactions, manages products and accounts, and maintains the security of the
  ITSO environment." Part 4 is the HOPS specification
  ([ITSO Part 4 HOPS](https://www.itso.org.uk/download/42205.8/part-4-hops)).
- Part 10 (Customer Media Definitions) "maps the logical ITSO Shell structure onto
  specific card technologies, covering memory layouts and command interactions,"
  distinguishing full and compact ITSO Shell implementations by media capability.
  Current version 2.1.5, dated 2025-03-31. Its revision history adds "placeholders
  for DESFire and Calypso" and lists "Mifare Standard 1K as obsolete"
  ([ITSO Part 10](https://www.itso.org.uk/download/42069.3/part-10-customer-media-definitions)).
- The 2.1.5 update adds "support for DESFire card emulation in Apple Wallet...
  enhanced contactless polling (v2.3), and acceptance of CMD11 and CMD12
  commands."
- Real-world DESFire migration: TfL moved Oyster off MIFARE Classic toward DESFire.
  Cards hold both Oyster and the ITSO application
  ([NFC Times](https://nfctimes.com/news/transport-london-discard-mifare-classic-seeks-desfire-sims)).

Inference: on the cVEND reader, the Itso(9) handler implements the ITSO Shell
read/verify flow. Select the ITSO Shell on the card (on DESFire this is a DESFire
application and file set per Part 10), use the ISAM to authenticate and validate
the IPEs, and log the transaction. The reader needs an ISAM (through FEIG's SAM
sockets; see the FEIG docs) to do ITSO security. That is consistent with the ITSO
architecture.

ITSO-on-DESFire means the Itso(9) and Desfire(7) handlers overlap at the chip
level. DESFire is the physical platform; the ITSO Shell is the logical application
carried in DESFire files. The separate Desfire(7) handler likely covers generic or
other DESFire applications. VDV-KA is also DESFire-based; see below.

Gaps: the Part 10 DESFire file and AID layout (which DESFire AID, file IDs, and key
settings carry the ITSO Shell) could not be retrieved. Part 10 is a public PDF but
was not fetched. Whether cVEND's DESFire-based ITSO is full or compact Shell is not
documented in the retrieved sources.

## Girogo

Girogo is a discontinued German contactless prepaid stored-value purse that ran on
the GeldKarte chip of Sparkassen and bank cards over NFC (ISO 14443, 13.56 MHz). It
was a closed, offline, on-card balance scheme, not open-loop EMV payment. It was
wound down between 2020 and 2024/2025.

Findings:

- Girogo is "a contactless prepaid payment function on Sparkassen-Cards (debit
  cards)." GeldKarte technology handles contact payments; girogo handles
  contactless ones
  ([Sparkasse GeldKarte FAQ](https://www.sparkasse.de/unsere-loesungen/privatkunden/karten/geldkarte.html)).
- The balance is stored on the chip and must be loaded beforehand, typically at an
  ATM, with a usual limit of about 200 euros per top-up. The card must be held
  within 4 cm of the reader
  ([CIO.de girogo](https://www.cio.de/article/3668857/kontaktloses-bezahlen-mit-girogo.html)).
- GeldKarte dates to 1996. The prepaid girogo variant has existed since the 2012
  introduction of NFC cards
  ([Wikipedia: GeldKarte](https://en.wikipedia.org/wiki/GeldKarte)).
- Discontinued: the GeldKarte and girogo function was phased out starting July 1
  2020. Remaining cards lost validity on December 31 2024. Acceptance at
  non-Sparkasse points was possible until June 30 2025. Wikipedia states the system
  was abandoned in December 2024
  ([Sparkasse FAQ](https://www.sparkasse.de/unsere-loesungen/privatkunden/karten/geldkarte.html);
  [Wikipedia: GeldKarte](https://en.wikipedia.org/wiki/GeldKarte)).

Inference: the Girogo(8) handler reads the on-card stored-value purse. It selects
the GeldKarte/girogo application over ISO 14443, reads the balance, and performs
the offline purse debit with scheme keys, likely needing a SAM. Because girogo is
now defunct, this handler on firmware 02.35 is likely a legacy German-market
capability that is dormant in current deployments.

Gap: no retrieved source documents the girogo command set, APDU-level purse-debit
protocol, or key management. That would require the German ZKA/Deutsche
Kreditwirtschaft GeldKarte spec.

## VDV-KA

VDV-KA (VDV-Kernapplikation, or VDV Core Application) is Germany's national
interoperable transit e-ticketing standard, branded eTicket Deutschland, first
released in 2005. The ticketing entitlement is the Berechtigung (EFS, or
Elektronischer Fahrschein, stored in TLV format), with an application logbook. It
runs on microprocessor smartcards over contact (ISO 7816) or contactless (ISO/IEC
14443) interfaces. MIFARE DESFire is a common carrier platform, though the original
reference chips were higher-end microcontrollers (NXP SmartMX with RSA). DESFire
usage is documented for the ecosystem, but the exact certified-chip mapping was not
pinned down.

Findings:

- VDV-KA was "first released in 2005 by a company set up to develop the eTicket
  Deutschland brand," and has been developed further since
  ([Intelligent Transport](https://www.intelligenttransport.com/transport-articles/10003/eticket-germany/)).
- The VDV Core Application "can run on chip cards using a high-performance
  microprocessor and standard contact or contactless interfaces (ISO 7816 / ISO
  14443)"
  ([Intelligent Transport (2005)](https://www.intelligenttransport.com/transport-articles/1559/e-ticketing-in-germany/)).
- An eTicket fare transaction is stored "on the chip card, in the Berechtigung
  (authorization) and in the application logbook" (Applikationslogbuch)
  ([VDV control-verification doc, 2017](https://media.frag-den-staat.de/files/foi/565526/20171122KontrollnachweiseEFS_geschwaerzt.pdf)).
- Inspection generates control records (TXEBER/TXEMBER) carrying a MAC as a
  tamper check, plus a sequence-number check (berLogSeqNummer) to confirm no
  transactions are missing.
- The EFS uses TLV. The Deutschlandticket technical requirements describe a
  Multi-Berechtigung variant needing an authentication key (KID 30, organisation ID
  5900) in the key store, and a tag 0xD6 "sceId"
  ([KCD-NRW Technische Anforderung Deutschlandticket V1.4/V1.9](https://www.kcd-nrw.de/fileadmin/user_upload/Technische_Anforderung_Deutschlandticket_V1.4.pdf)).
- NXP supplied SmartMX contactless microcontrollers for VDV-KA, meeting VDV
  security requirements "including RSA-based public key cryptography"
  ([NS Energy / NXP](https://www.nsenergybusiness.com/)).
- MIFARE DESFire EV1/EV3 is ISO/IEC 14443 Type A, ISO 14443-4 transmission, used
  widely in German transit for fare purses, access, and time recording, with up to
  about 28 applications on EV1
  ([NXP DESFire EV3 datasheet](https://www.crz.gov.sk//data/att/4664173.pdf);
  [InterCard DESFire EV1 (2009)](https://www.unimagazin.ovgu.de/unimagdeburg_media/Studium/Studierende/Info_DES_Fire-p-3343.pdf)).
- A successor standard, eTiCore, is due from 2027
  ([TED notice 228926-2026](https://ted.europa.eu/en/notice/228926-2026/pdf)).

Inference: the VdvKa(4) handler selects the VDV-KA application on the card (DESFire
hosted in most modern deployments), reads the Berechtigung/EFS TLV, validates its
MAC or signature with a SAM-held key, and writes the application logbook and
control record on validation. That is why VdvKa(4) and Desfire(7) overlap again:
DESFire is the carrier, VDV-KA the logical application. VDV-KA on the reader needs
the VDV key hierarchy in a SAM; the TXEBER/TXEMBER MAC and KID-based keys imply
symmetric key material the validator must hold securely.

Gaps: the VDV-KA spec's DESFire application layout (AID and file structure for
Berechtigung versus logbook) could not be retrieved. The normative VDV-KA and
KA-Chipkarte documents were not in results. Which DESFire generations are formally
certified for current VDV-KA is unconfirmed; sources show both SmartMX
microcontrollers and DESFire in the ecosystem.

## FEIG's marketing for these schemes

FEIG markets cVEND as a single multi-application transit validator that reads
open-loop EMV and wallets plus closed-loop schemes (MIFARE, CIPURSE, ITSO, VDV-KA,
Calypso) "with the same priority" and "in parallel." It is EMVCo L1/L2 and PCI PTS
certified, a Visa Ready for Transit partner, with multiple Level 2 payment kernels
and SAM sockets. All claims below are vendor-reported.

Findings:

- cVEND's "Multi-Application architecture supports open-loop contactless payment
  cards and mobile wallets... as well as closed-loop cards like MIFARE, CIPURSE,
  ITSO, VDV-KA, or Calypso with the same priority." "Closed-loop e-tickets and
  open-loop payment cards can be read in parallel at high performance"
  ([FEIG cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)).
- The cVEND plug is "fully approved for open-loop payment by EMVCo and PCI PTS."
  "A step-by-step upgrade concept enables migration from closed-loop to open-loop."
- cVEND terminals "use eight independent application directories to process open
  loop payment applications in parallel with closed loop ticketing," and support
  "common RFID chips like Mifare, Felica, etc."
  ([FEIG press: multi-application technique](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/)).
- Terminals are "certified according to EMVCo Level 1 and PCI PTS 4.0, and include
  Level 2 kernels for American Express, Discover, Mastercard and VISA." FEIG's
  transit page cites the multi-application architecture and four SAM sockets.
- FEIG joined the Visa Ready for Transit program in May 2020. The cVEND family has
  "certified kernels for VISA, American Express, Discover, Mastercard, RuPay and
  MADA (PURE)," with EMVCo Level 1 and Level 2 certification
  ([FEIG Visa Ready for Transit release](https://www.FEIG.de/fileadmin/user_upload/Downloads/News/2020-06-02-VISA-Ready-for-Transit-EN.pdf)).
- Product family: cVEND plug, box, box+, PIN, touch. cVEND compact II is a retrofit
  platform with an integrated LTE modem and antenna and an MDB interface, for app
  development
  ([FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).

Inference: FEIG's "eight independent application directories" is the marketing
description of the ProxCard handler slot mechanism the firmware exposes. VdvKa,
MifareClassic, Iso, Desfire, Girogo, Itso, and UltralightC are seven of the
closed-loop handlers; EMV is the open-loop path through EmvReader and the Entry
Point. The handler index numbers 4 to 10 are consistent with a fixed table of
directory slots. The four SAM sockets provide per-scheme secure key storage (ITSO
ISAM, VDV-KA keys, Calypso/MIFARE keys, girogo/GeldKarte keys) needed to
authenticate each closed-loop scheme.

Gap: no FEIG-published scheme-specific application note, such as a dedicated
"cVEND plus ITSO" or "cVEND plus VDV-KA" integration whitepaper, was located. Only
datasheets and press releases. FEIG's deeper integration docs appear to be behind
partner or login gating.

## ProxCard handlers and the multi-application reader

A multi-application reader enables several card-scheme handlers simultaneously. On
each card presentation it runs ISO 14443 anticollision, then dispatches to the
handler or handlers whose scheme the card matches. The enabled handler performs
scheme-specific selection and authentication with SAM keys. This is documented at
the concept level by FEIG's "parallel application directories" and by the general
multi-application MIFARE problem. The specific `RFIDReaderMultiApp` class name was
not found in public sources; it is firmware-internal.

Findings:

- FEIG runs "eight independent application directories to process open loop... in
  parallel with closed loop ticketing," designed for "maximum possible transaction
  speed" at access barriers
  ([FEIG press](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/)).
- Background: multi-application cards' "multi-applications feature causes problems
  with increased access times," the latency problem a parallel reader architecture
  addresses
  ([NXP MIFARE4Mobile blog](https://www.nxp.com/company/about-nxp/smarter-world-blog/BL-MIFARE4MOBILE-GIVES-SMARTPHONES-MULTI-APP)).
- Masabi's validator and FEIG's cVEND both describe open-architecture or
  multi-format reading (barcode, NFC smartcard, contactless EMV) in one device
  ([Masabi Justride](https://www.masabi.com/account-based-ticketing/);
  [FEIG cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)).

Inference: enabling a handler in the firmware most plausibly means registering that
scheme's directory slot so that, after RF anticollision, SAK, and ATS, the reader
attempts that scheme's application SELECT and, on success, holds the card and runs
the scheme's authentication (DESFire AES/3DES auth, ITSO ISAM challenge, VDV-KA MAC
verification, girogo purse keys, MIFARE Classic sector-key auth). Handlers not
enabled are skipped, reducing per-tap latency. That follows from the FEIG parallel
directory model and known per-scheme auth.

The numeric indices (VdvKa 4, MifareClassic 5, Iso 6, Desfire 7, Girogo 8, Itso 9,
UltralightC 10) look like a fixed handler-type enum. Indices 0 to 3, not in the
enabled list, are likely other or base handler types (none, raw, EMV, FeliCa). Iso
6 is probably a generic ISO 14443-4 / ISO 7816 APDU handler used as a base for the
higher schemes. This is inference and not independently sourced.

Gap: no public documentation of FEIG's internal `RFIDReaderMultiApp` or ProxCard
handler class model. It is firmware-internal and only inferable from the
reverse-engineered symbols plus FEIG's marketing description of parallel
directories.

## Account-based ticketing and the backend

In ABT, the fare logic lives in the cloud, not on the card. The card, phone, or EMV
card is just a token, an identifier bound to a back-office account. The validator
captures the token at tap, sends it to the backend, and the backend computes the
fare, including fare capping and best value. A validator like Masabi's Justride
reads barcodes, NFC smartcards, and contactless EMV and integrates with the cloud
platform. Masabi material is well documented; Bytemark specifics were not found in
results.

Findings:

- Masabi's Justride platform "is account based and supports multiple tokens
  assigned to a back office account, so passengers no longer need to buy a ticket
  before traveling"
  ([Masabi: account-based ticketing](https://blog.masabi.com/blog/everything-you-need-to-know-about-account-based-ticketing)).
- In ABT, "each form of transport medium has a back-office account assigned to it.
  Information is transmitted to this system when used at a validator or gate to make
  fare adjustments as needed."
- The Justride Validator is a multi-format device supporting "paper and mobile
  barcodes, contactless bank cards (cEMV) and smartcards (NFC), as well as
  bluetooth," with an "open-architecture design [for] easy integration with
  third-party software"
  ([Finextra: Masabi multi-format validator](https://finextra.com/pressarticle/78732/masabi-unveils-multi-format-scanning-device-for-contactless-tap-and-ride-ticketing);
  [Masabi ABT](https://www.masabi.com/account-based-ticketing/)).
- Deployment example: SkyBus in Australia launched ABT with Fujitsu and Masabi,
  with Justride Validators installed fleet-wide
  ([Masabi / SkyBus](https://www.masabi.com/2022/03/29/skybus-launches-new-fare-payment-system-provided-by-fujitsu-and-masabi/)).

Inference: a cVEND-class validator in an ABT deployment uses the EMV Entry Point
only far enough to capture a token from the open-loop card (the PAN or token through
a zero-amount or status-check flow), then hands that token to the backend
(Masabi/Bytemark), which does fare calculation and deferred authorization and
settlement. This matches the earlier inference that EMV Pre-Processing is
configured for a zero-amount or deferred transit flow rather than a point-of-sale
sale.

For closed-loop schemes (ITSO, VDV-KA), the same validator can operate card-based,
reading the entitlement from the chip, or token-based, using the card UID or PAN as
an ABT account token. That dual nature is normal for multi-application transit
readers.

Gaps: no Bytemark-specific documentation surfaced, only Masabi. Validator-to-backend
API and message formats, token-to-account binding, and fare-calculation service
internals were not found in public sources for either vendor. No source explicitly
connects FEIG cVEND to Masabi or Bytemark backends, though FEIG hardware is commonly
paired with such platforms. That was not confirmed in results.
