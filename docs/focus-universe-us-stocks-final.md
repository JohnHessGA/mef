# Focus US Stocks (Final) — 305 Symbols

The final curated study universe of US stocks with a liquid listed-options market. This is the working set derived from the 782-symbol focus universe by successive quality / liquidity / market-cap / options filters.

**Preceding docs in the chain:**
- `focus-universe.md` — full 782-symbol focus universe
- `focus-universe-us-stocks-liquid.md` — 600 (price > \$10, vol > 300K)
- `focus-universe-us-stocks-filtered.md` — 433 (adds price > \$20, \$ vol ≥ \$50M, mcap ≥ \$15B)
- `focus-universe-us-stocks-options.md` — 432 (adds ≥ 2 expirations, total OI ≥ 500)
- **This file — 305 (raises market-cap floor to \$30B)**

## Filter Criteria (all applied)

- Stock from the 782-symbol focus universe (ETFs / ADRs excluded)
- Avg close > **\$20** over the last 90 bar-days (through 2026-04-13)
- Avg daily share volume > **300K**
- Avg daily dollar volume ≥ **\$50M**
- Market cap ≥ **\$30B** (latest `shdb.stock_valuation_1q`, period_end 2026-03-31)
- ≥ 2 distinct options expirations in `shdb.options_snapshot_1d` (2026-04-16)
- Total open interest across all contracts ≥ 500

## Sector Distribution

| Sector | Count |
|--------|------:|
| Technology | 60 |
| Industrials | 49 |
| Financial Services | 45 |
| Healthcare | 36 |
| Consumer Cyclical | 25 |
| Consumer Defensive | 17 |
| Communication Services | 16 |
| Utilities | 15 |
| Energy | 15 |
| Real Estate | 15 |
| Basic Materials | 12 |
| **Total** | **305** |

**Last regenerated:** 2026-04-19

## Stock List

Sorted alphabetically.

| Symbol | Name | Sector | Industry | Avg Close | Avg Vol | Avg $ Vol | Market Cap | Expirations | Total OI |
|--------|------|--------|----------|----------:|--------:|----------:|-----------:|------------:|---------:|
| A | Agilent Technologies Inc. | Healthcare | Diagnostics & Research | $123.28 | 2,204,554 | $272M | $38.0B | 10 | 21,211 |
| AAPL | Apple Inc. | Technology | Consumer Electronics | $259.66 | 46,913,776 | $12.18B | $4.05T | 25 | 4,508,974 |
| ABBV | ABBVIE INC. | Healthcare | Drug Manufacturers - General | $219.93 | 7,132,062 | $1.57B | $410.3B | 19 | 253,296 |
| ABNB | Airbnb, Inc. Class A Common Stock | Consumer Cyclical | Travel Services | $128.94 | 4,547,350 | $586M | $75.4B | 17 | 239,154 |
| ABT | Abbott Laboratories | Healthcare | Medical Devices | $110.03 | 11,762,235 | $1.29B | $238.1B | 16 | 183,480 |
| ACGL | Arch Capital Group Ltd | Financial Services | Insurance - Diversified | $96.04 | 2,022,590 | $194M | $34.1B | 5 | 5,129 |
| ACN | Accenture PLC | Technology | Information Technology Services | $223.25 | 6,875,786 | $1.54B | $130.0B | 15 | 146,689 |
| ADBE | Adobe Inc. | Technology | Software - Application | $265.50 | 5,975,867 | $1.59B | $107.9B | 19 | 540,393 |
| ADI | Analog Devices, Inc. | Technology | Semiconductors | $323.70 | 4,000,130 | $1.29B | $152.8B | 14 | 76,850 |
| ADP | Automatic Data Processing | Technology | Software - Application | $221.84 | 3,695,082 | $820M | $104.1B | 15 | 45,415 |
| ADSK | Autodesk Inc | Technology | Software - Application | $245.15 | 2,320,170 | $569M | $64.8B | 16 | 38,451 |
| AEP | American Electric Power Company, Inc. | Utilities | Utilities - Regulated Electric | $127.36 | 3,502,646 | $446M | $60.5B | 10 | 50,998 |
| AFL | Aflac Inc. | Financial Services | Insurance - Life | $110.93 | 2,411,145 | $267M | $59.4B | 16 | 41,542 |
| AIG | American International Group, Inc. | Financial Services | Insurance - Diversified | $76.27 | 4,236,106 | $323M | $43.9B | 16 | 98,942 |
| ALL | The Allstate Corporation | Financial Services | Insurance - Property & Casualty | $205.35 | 1,626,748 | $334M | $57.2B | 9 | 22,532 |
| ALNY | Alnylam Pharmaceuticals, Inc. | Healthcare | Biotechnology | $331.67 | 1,314,392 | $436M | $62.6B | 7 | 22,398 |
| AMAT | Applied Materials Inc | Technology | Semiconductor Equipment & Materials | $346.38 | 7,505,866 | $2.60B | $257.6B | 19 | 324,140 |
| AMD | Advanced Micro Devices | Technology | Semiconductors | $215.64 | 38,272,922 | $8.25B | $261.7B | 22 | 3,102,115 |
| AME | Ametek, Inc. | Industrials | Specialty Industrial Machinery | $223.96 | 1,397,254 | $313M | $43.6B | 6 | 10,816 |
| AMGN | Amgen Inc | Healthcare | Drug Manufacturers - General | $358.62 | 2,821,881 | $1.01B | $153.0B | 16 | 102,460 |
| AMP | Ameriprise Financial, Inc. | Financial Services | Asset Management | $474.26 | 717,564 | $340M | $48.0B | 5 | 4,764 |
| AMT | American Tower Corporation | Real Estate | REIT - Specialty | $180.33 | 3,344,702 | $603M | $90.2B | 10 | 46,884 |
| AMZN | Amazon.Com Inc | Consumer Cyclical | Internet Retail | $218.20 | 50,880,842 | $11.10B | $2.38T | 26 | 5,083,363 |
| ANET | Arista Networks | Technology | Computer Hardware | $134.82 | 7,835,353 | $1.06B | $186.0B | 17 | 301,353 |
| AON | Aon plc Class A | Financial Services | Insurance Brokers | $329.19 | 1,527,525 | $503M | $77.3B | 5 | 6,537 |
| APD | Air Products & Chemicals, Inc. | Basic Materials | Specialty Chemicals | $280.06 | 1,469,586 | $412M | $55.1B | 7 | 28,120 |
| APH | Amphenol Corporation | Technology | Electronic Components | $139.91 | 10,197,708 | $1.43B | $158.7B | 12 | 156,836 |
| APO | Apollo Global Management, Inc. | Financial Services | Asset Management | $119.17 | 5,412,705 | $645M | $81.0B | 14 | 364,923 |
| APP | Applovin Corporation Class A Common Stock | Communication Services | Advertising Agencies | $455.42 | 6,203,718 | $2.83B | $245.0B | 18 | 325,121 |
| AVGO | Broadcom Inc. Common Stock | Technology | Semiconductors | $328.99 | 26,594,634 | $8.75B | $1.62T | 26 | 1,880,884 |
| AXON | Axon Enterprise, Inc. Common Stock | Industrials | Aerospace & Defense | $491.80 | 1,080,132 | $531M | $56.3B | 13 | 52,141 |
| AXP | American Express Company | Financial Services | Credit Services | $327.52 | 3,636,777 | $1.19B | $230.2B | 20 | 255,764 |
| BA | Boeing Company | Industrials | Aerospace & Defense | $225.66 | 7,191,097 | $1.62B | $158.5B | 18 | 925,929 |
| BAC | Bank of America Corporation | Financial Services | Banks - Diversified | $51.04 | 41,913,470 | $2.14B | $393.5B | 22 | 2,624,653 |
| BDX | Becton, Dickinson and Co. | Healthcare | Medical Instruments & Supplies | $177.89 | 2,621,134 | $466M | $55.5B | 8 | 8,680 |
| BK | Bank of New York Mellon Corporation | Financial Services | Banks - Diversified | $119.66 | 3,774,442 | $452M | $77.7B | 8 | 63,038 |
| BKNG | Booking Holdings Inc. Common Stock | Consumer Cyclical | Travel Services | $4132.34 | 1,107,035 | $4.57B | $175.8B | 19 | 580,003 |
| BLK | Blackrock, Inc. | Financial Services | Asset Management | $1038.57 | 877,015 | $911M | $192.6B | 17 | 39,336 |
| BMY | Bristol-Myers Squibb Co. | Healthcare | Drug Manufacturers - General | $58.78 | 13,113,983 | $771M | $92.0B | 17 | 551,046 |
| BRO | Brown & Brown, Inc. | Financial Services | Insurance Brokers | $70.49 | 3,467,785 | $244M | $31.1B | 5 | 5,456 |
| BSX | Boston Scientific Corp. | Healthcare | Medical Devices | $75.80 | 16,707,153 | $1.27B | $146.0B | 17 | 400,976 |
| BX | Blackstone Inc. | Financial Services | Asset Management | $125.05 | 8,588,535 | $1.07B | $133.7B | 21 | 408,979 |
| C | Citigroup Inc. | Financial Services | Banks - Diversified | $113.95 | 15,125,564 | $1.72B | $189.1B | 19 | 1,441,137 |
| CAH | Cardinal Health, Inc. | Healthcare | Medical Distribution | $216.38 | 1,746,694 | $378M | $48.7B | 13 | 36,539 |
| CARR | Carrier Global Corporation | Industrials | Building Products & Equipment | $59.73 | 7,394,458 | $442M | $51.3B | 9 | 121,861 |
| CAT | Caterpillar Inc. | Industrials | Farm & Heavy Construction Machinery | $709.58 | 2,804,198 | $1.99B | $224.6B | 18 | 224,460 |
| CB | Chubb Limited | Financial Services | Insurance - Property & Casualty | $323.17 | 1,730,240 | $559M | $113.1B | 11 | 29,704 |
| CBRE | CBRE GROUP, INC. | Real Estate | Real Estate Services | $148.88 | 2,318,648 | $345M | $47.3B | 6 | 21,261 |
| CCI | Crown Castle Inc. | Real Estate | REIT - Specialty | $85.98 | 3,476,815 | $299M | $42.2B | 10 | 30,260 |
| CCL | Carnival Corporation | Consumer Cyclical | Travel Services | $28.57 | 25,393,222 | $726M | $43.9B | 16 | 1,174,339 |
| CDNS | Cadence Design Systems | Technology | Software - Application | $293.89 | 2,545,180 | $748M | $96.2B | 16 | 82,049 |
| CEG | Constellation Energy Corporation Common Stock | Utilities | Utilities - Independent Power Producers | $296.22 | 3,721,761 | $1.10B | $103.0B | 17 | 208,562 |
| CHTR | Charter Comm Inc Del CL A New | Communication Services | Telecom Services | $218.08 | 1,920,150 | $419M | $37.5B | 13 | 130,206 |
| CI | The Cigna Group | Healthcare | Healthcare Plans | $275.82 | 1,719,030 | $474M | $77.1B | 15 | 85,608 |
| CL | Colgate-Palmolive Company | Consumer Defensive | Household & Personal Products | $89.70 | 6,818,070 | $612M | $64.8B | 15 | 96,481 |
| CMCSA | Comcast Corp | Communication Services | Telecom Services | $29.85 | 33,763,670 | $1.01B | $115.9B | 17 | 866,060 |
| CME | CME Group Inc. | Financial Services | Financial Data & Stock Exchanges | $301.02 | 2,302,697 | $693M | $97.4B | 14 | 56,178 |
| CMG | Chipotle Mexican Grill, Inc. | Consumer Cyclical | Restaurants | $36.32 | 16,910,864 | $614M | $52.5B | 15 | 835,952 |
| CMI | Cummins Inc. | Industrials | Specialty Industrial Machinery | $570.54 | 948,998 | $541M | $58.6B | 7 | 18,274 |
| COF | Capital One Financial | Financial Services | Credit Services | $201.96 | 5,595,063 | $1.13B | $135.9B | 15 | 189,227 |
| COHR | Coherent Corp. | Technology | Scientific & Technical Instruments | $239.70 | 7,291,041 | $1.75B | $35.6B | 15 | 135,055 |
| COIN | Coinbase Global, Inc. Class A Common Stock | Financial Services | Financial Data & Stock Exchanges | $188.24 | 12,511,106 | $2.36B | $98.5B | 21 | 1,209,221 |
| COP | ConocoPhillips | Energy | Oil & Gas E&P | $114.41 | 9,809,366 | $1.12B | $117.9B | 19 | 412,224 |
| COR | Cencora, Inc. | Healthcare | Medical Distribution | $346.59 | 1,339,521 | $464M | $66.0B | 10 | 16,316 |
| COST | Costco Wholesale Corp | Consumer Defensive | Discount Stores | $987.81 | 2,085,815 | $2.06B | $452.6B | 19 | 261,538 |
| CP | Canadian Pacific Kansas City Limited | Industrials | Railroads | $79.94 | 2,873,929 | $230M | $67.9B | 6 | 25,344 |
| CPRT | Copart Inc | Industrials | Specialty Business Services | $36.84 | 9,282,642 | $342M | $39.6B | 10 | 66,472 |
| CRH | CRH Public Limited Company | Basic Materials | Building Materials | $115.45 | 5,289,788 | $611M | $81.0B | 11 | 42,722 |
| CRM | Salesforce, Inc. | Technology | Software - Application | $197.52 | 13,761,695 | $2.72B | $248.5B | 19 | 903,462 |
| CRWD | CrowdStrike Holdings, Inc. Class A Common Stock | Technology | Software - Infrastructure | $416.52 | 4,137,583 | $1.72B | $136.5B | 21 | 396,140 |
| CSCO | Cisco Systems, Inc. Common Stock (DE) | Technology | Communication Equipment | $79.05 | 23,985,362 | $1.90B | $297.2B | 17 | 700,647 |
| CSGP | CoStar Group Inc | Real Estate | Real Estate Services | $49.12 | 6,909,991 | $339M | $34.1B | 10 | 67,289 |
| CSX | CSX Corporation | Industrials | Railroads | $39.94 | 13,641,280 | $545M | $66.3B | 17 | 230,702 |
| CTAS | Cintas Corp | Industrials | Specialty Business Services | $189.71 | 2,240,402 | $425M | $81.4B | 15 | 19,699 |
| CTSH | Cognizant Technology Solutions | Technology | Information Technology Services | $68.76 | 6,746,580 | $464M | $38.4B | 10 | 37,876 |
| CTVA | Corteva, Inc. Common Stock | Basic Materials | Agricultural Inputs | $77.22 | 4,258,752 | $329M | $45.9B | 6 | 18,404 |
| CVS | CVS HEALTH CORPORATION | Healthcare | Healthcare Plans | $76.60 | 8,821,038 | $676M | $95.7B | 16 | 398,310 |
| CVX | Chevron Corporation | Energy | Oil & Gas Integrated | $186.59 | 12,826,543 | $2.39B | $302.2B | 16 | 610,251 |
| D | Dominion Energy, Inc Common Stock | Utilities | Utilities - Regulated Electric | $62.33 | 5,233,828 | $326M | $52.3B | 10 | 106,691 |
| DAL | Delta Air Lines, Inc. | Industrials | Airlines | $66.86 | 11,696,715 | $782M | $43.3B | 14 | 711,837 |
| DASH | DoorDash, Inc. Class A Common Stock | Consumer Cyclical | Internet Retail | $176.71 | 5,020,725 | $887M | $120.2B | 16 | 161,799 |
| DD | DuPont de Nemours, Inc. Common Stock | Basic Materials | Specialty Chemicals | $46.41 | 4,555,532 | $211M | $32.7B | 10 | 48,673 |
| DDOG | Datadog, Inc. Class A Common Stock | Technology | Software - Application | $121.24 | 5,831,004 | $707M | $51.5B | 17 | 271,124 |
| DE | Deere & Company | Industrials | Farm & Heavy Construction Machinery | $576.98 | 1,584,978 | $914M | $143.0B | 15 | 53,542 |
| DELL | Dell Technologies Inc. | Technology | Computer Hardware | $140.34 | 8,680,250 | $1.22B | $87.3B | 21 | 564,132 |
| DHI | D.R. Horton Inc. | Consumer Cyclical | Residential Construction | $150.11 | 2,942,673 | $442M | $42.2B | 15 | 57,367 |
| DHR | Danaher Corporation | Healthcare | Diagnostics & Research | $207.74 | 4,177,812 | $868M | $131.9B | 14 | 65,464 |
| DIS | The Walt Disney Company | Communication Services | Entertainment | $103.80 | 11,635,170 | $1.21B | $203.6B | 19 | 651,729 |
| DLR | Digital Realty Trust, Inc. | Real Estate | REIT - Specialty | $174.44 | 2,029,870 | $354M | $60.4B | 15 | 40,009 |
| DUK | Duke Energy Corporation | Utilities | Utilities - Regulated Electric | $126.78 | 4,569,095 | $579M | $96.3B | 11 | 88,049 |
| EA | Electronic Arts Inc | Communication Services | Electronic Gaming & Multimedia | $201.78 | 2,555,605 | $516M | $51.7B | 21 | 198,549 |
| EBAY | eBay Inc | Consumer Cyclical | Internet Retail | $90.53 | 5,316,725 | $481M | $42.5B | 15 | 100,901 |
| ECL | Ecolab, Inc. | Basic Materials | Specialty Chemicals | $282.14 | 1,443,162 | $407M | $78.2B | 6 | 10,242 |
| ED | Consolidated Edison, Inc. | Utilities | Utilities - Regulated Electric | $110.05 | 2,229,114 | $245M | $36.4B | 7 | 15,565 |
| EFX | Equifax, Incorporated | Industrials | Consulting Services | $194.27 | 1,859,830 | $361M | $31.8B | 6 | 60,471 |
| EL | The Estee Lauder Companies Inc. Class A | Consumer Defensive | Household & Personal Products | $97.40 | 4,909,036 | $478M | $38.2B | 15 | 205,477 |
| ELV | Elevance Health, Inc. | Healthcare | Healthcare Plans | $321.71 | 1,948,846 | $627M | $72.3B | 9 | 33,661 |
| EMR | Emerson Electric Co. | Industrials | Specialty Industrial Machinery | $143.20 | 3,477,406 | $498M | $74.9B | 13 | 55,910 |
| ENB | Enbridge, Inc | Energy | Oil & Gas Midstream | $51.90 | 5,214,106 | $271M | $110.4B | 7 | 48,055 |
| EOG | EOG Resources, Inc. | Energy | Oil & Gas E&P | $125.57 | 5,439,211 | $683M | $61.0B | 16 | 142,799 |
| EQIX | Equinix, Inc. Common Stock REIT | Real Estate | REIT - Specialty | $918.09 | 634,702 | $583M | $78.0B | 8 | 17,896 |
| EQT | EQT CORP | Energy | Oil & Gas E&P | $59.39 | 9,762,524 | $580M | $34.2B | 14 | 296,862 |
| ETN | Eaton Corporation, plc Ordinary Shares | Industrials | Specialty Industrial Machinery | $362.59 | 2,792,880 | $1.01B | $146.0B | 16 | 79,657 |
| ETR | Entergy Corporation | Utilities | Utilities - Regulated Electric | $103.36 | 2,811,562 | $291M | $42.3B | 7 | 22,328 |
| EW | Edwards Lifesciences Corp | Healthcare | Medical Devices | $81.89 | 4,706,315 | $385M | $45.5B | 10 | 47,386 |
| EXC | Exelon Corporation | Utilities | Utilities - Regulated Electric | $47.18 | 8,887,123 | $419M | $45.6B | 10 | 66,192 |
| EXR | Extra Space Storage, Inc. | Real Estate | REIT - Industrial | $140.97 | 1,324,723 | $187M | $31.2B | 5 | 4,801 |
| FANG | Diamondback Energy, Inc. | Energy | Oil & Gas E&P | $175.22 | 3,054,061 | $535M | $41.3B | 9 | 80,514 |
| FAST | Fastenal Co | Industrials | Industrial Distribution | $45.56 | 8,817,739 | $402M | $56.4B | 10 | 105,454 |
| FCX | Freeport-McMoran Inc. | Basic Materials | Copper | $61.45 | 20,107,567 | $1.24B | $56.6B | 17 | 1,187,375 |
| FDX | FedEx Corporation | Industrials | Integrated Freight & Logistics | $354.34 | 1,937,203 | $686M | $92.5B | 16 | 91,308 |
| FICO | Fair Isaac Corporation | Technology | Software - Application | $1302.03 | 356,623 | $464M | $40.5B | 11 | 22,667 |
| FIS | Fidelity National Information Services, Inc. | Technology | Information Technology Services | $51.31 | 5,953,205 | $305M | $34.5B | 15 | 34,394 |
| FISV | Fiserv, Inc. Common Stock | Technology | Information Technology Services | $60.45 | 8,315,772 | $503M | $71.4B | 12 | 291,564 |
| FOXA | Fox Corporation Class A Common Stock | Communication Services | Entertainment | $62.10 | 4,202,958 | $261M | $32.2B | 6 | 12,644 |
| FTNT | Fortinet, Inc. | Technology | Software - Infrastructure | $81.06 | 6,862,125 | $556M | $64.0B | 15 | 190,025 |
| GD | General Dynamics Corporation | Industrials | Aerospace & Defense | $353.79 | 1,361,607 | $482M | $90.1B | 16 | 29,839 |
| GE | GE Aerospace | Industrials | Aerospace & Defense | $311.41 | 5,790,598 | $1.80B | $320.4B | 15 | 207,702 |
| GEHC | GE HealthCare Technologies Inc. Common Stock | Healthcare | Medical Devices | $77.16 | 3,674,562 | $284M | $34.3B | 15 | 47,530 |
| GEV | GE Vernova Inc. | Industrials | Specialty Industrial Machinery | $814.19 | 2,771,848 | $2.26B | $169.1B | 18 | 187,501 |
| GILD | Gilead Sciences Inc | Healthcare | Drug Manufacturers - General | $142.14 | 7,091,000 | $1.01B | $139.2B | 19 | 159,228 |
| GLW | Corning Incorporated | Technology | Electronic Components | $129.16 | 11,994,168 | $1.55B | $71.2B | 17 | 299,253 |
| GM | General Motors Company | Consumer Cyclical | Auto Manufacturers | $78.56 | 8,119,615 | $638M | $58.8B | 14 | 330,265 |
| GOOG | Alphabet Inc. Class C Capital Stock | Communication Services | Internet Content & Information | $312.31 | 21,620,880 | $6.75B | $2.97T | 20 | 1,733,403 |
| GOOGL | Alphabet Inc. Class A Common Stock | Communication Services | Internet Content & Information | $312.67 | 33,482,222 | $10.47B | $2.97T | 25 | 2,984,742 |
| GRMN | Garmin Ltd | Technology | Scientific & Technical Instruments | $228.69 | 960,157 | $220M | $40.3B | 6 | 13,033 |
| GS | Goldman Sachs Group Inc. | Financial Services | Capital Markets | $885.45 | 2,452,784 | $2.17B | $250.9B | 22 | 450,000 |
| HCA | HCA Healthcare, Inc. | Healthcare | Medical Care Facilities | $504.92 | 1,108,488 | $560M | $86.2B | 10 | 23,468 |
| HD | Home Depot, Inc. | Consumer Cyclical | Home Improvement Retail | $361.01 | 4,135,460 | $1.49B | $377.7B | 19 | 232,618 |
| HEI | HEICO Corporation | Industrials | Aerospace & Defense | $314.15 | 616,758 | $194M | $46.7B | 6 | 8,826 |
| HIG | The Hartford Insurance Group, Inc. | Financial Services | Insurance - Diversified | $136.58 | 1,570,207 | $214M | $38.0B | 5 | 7,118 |
| HLT | Hilton Worldwide Holdings Inc. | Consumer Cyclical | Lodging | $305.50 | 1,932,414 | $590M | $61.5B | 15 | 48,684 |
| HON | Honeywell International, Inc. | Industrials | Conglomerates | $231.66 | 4,199,113 | $973M | $149.3B | 15 | 158,657 |
| HOOD | Robinhood Markets, Inc. Class A Common Stock | Financial Services | Capital Markets | $82.11 | 29,881,356 | $2.45B | $131.4B | 19 | 1,978,716 |
| HUM | Humana Inc. | Healthcare | Healthcare Plans | $195.12 | 2,159,452 | $421M | $31.4B | 16 | 122,773 |
| HWM | Howmet Aerospace Inc. | Industrials | Aerospace & Defense | $236.70 | 2,606,111 | $617M | $79.5B | 15 | 50,738 |
| IBKR | Interactive Brokers Group, Inc. Class A Common Stock | Financial Services | Capital Markets | $71.32 | 5,064,708 | $361M | $30.7B | 13 | 131,121 |
| IBM | International Business Machines Corporation | Technology | Information Technology Services | $263.40 | 5,940,926 | $1.56B | $279.5B | 20 | 318,004 |
| ICE | Intercontinental Exchange  Inc. | Financial Services | Financial Data & Stock Exchanges | $163.09 | 3,900,338 | $636M | $96.7B | 13 | 31,810 |
| IDXX | Idexx Laboratories Inc | Healthcare | Diagnostics & Research | $625.68 | 519,880 | $325M | $34.4B | 6 | 2,822 |
| INSM | Insmed, Inc. | Healthcare | Biotechnology | $152.27 | 2,463,296 | $375M | $30.5B | 8 | 45,819 |
| INTC | Intel Corp | Technology | Semiconductors | $47.65 | 108,937,355 | $5.19B | $160.9B | 18 | 5,226,876 |
| INTU | Intuit Inc | Technology | Software - Application | $447.54 | 4,217,339 | $1.89B | $139.7B | 16 | 138,270 |
| IQV | IQVIA Holdings Inc. | Healthcare | Diagnostics & Research | $187.06 | 2,073,939 | $388M | $32.6B | 6 | 10,020 |
| IR | Ingersoll Rand Inc. Common Stock | Industrials | Specialty Industrial Machinery | $88.16 | 3,899,145 | $344M | $33.0B | 7 | 15,372 |
| IRM | Iron Mountain Inc. | Real Estate | REIT - Specialty | $101.83 | 1,794,507 | $183M | $30.4B | 15 | 41,639 |
| ISRG | Intuitive Surgical Inc. | Healthcare | Medical Instruments & Supplies | $491.16 | 1,936,537 | $951M | $161.8B | 19 | 87,128 |
| ITW | Illinois Tool Works Inc. | Industrials | Specialty Industrial Machinery | $273.51 | 1,429,903 | $391M | $76.1B | 7 | 12,694 |
| JCI | Johnson Controls International plc | Industrials | Building Products & Equipment | $131.88 | 4,655,279 | $614M | $73.5B | 10 | 96,179 |
| JNJ | Johnson & Johnson | Healthcare | Drug Manufacturers - General | $236.94 | 8,725,136 | $2.07B | $436.4B | 17 | 362,939 |
| JPM | JPMorgan Chase & Co. | Financial Services | Banks - Diversified | $300.53 | 11,090,757 | $3.33B | $873.0B | 20 | 733,550 |
| KDP | Keurig Dr Pepper Inc. | Consumer Defensive | Beverages - Non-Alcoholic | $27.81 | 10,773,417 | $300M | $34.8B | 10 | 71,635 |
| KEYS | Keysight Technologies, Inc. | Technology | Scientific & Technical Instruments | $262.72 | 1,482,392 | $389M | $37.4B | 8 | 19,434 |
| KHC | The Kraft Heinz Company Common Stock | Consumer Defensive | Packaged Foods | $23.44 | 16,633,630 | $390M | $30.3B | 16 | 424,102 |
| KLAC | KLA Corporation Common Stock | Technology | Semiconductor Equipment & Materials | $1495.83 | 1,099,366 | $1.64B | $160.4B | 9 | 33,987 |
| KMB | Kimberly-Clark Corp. | Consumer Defensive | Household & Personal Products | $102.03 | 5,701,328 | $582M | $41.4B | 16 | 104,692 |
| KMI | Kinder Morgan, Inc. | Energy | Oil & Gas Midstream | $31.91 | 14,306,678 | $457M | $63.0B | 14 | 336,103 |
| KO | Coca-Cola Company | Consumer Defensive | Beverages - Non-Alcoholic | $76.52 | 17,737,273 | $1.36B | $303.5B | 18 | 750,437 |
| KR | The Kroger Co. | Consumer Defensive | Grocery Stores | $68.81 | 6,760,784 | $465M | $42.5B | 16 | 119,850 |
| LEN | Lennar Corporation Class A | Consumer Cyclical | Residential Construction | $105.24 | 3,088,000 | $325M | $34.0B | 15 | 117,863 |
| LHX | L3Harris Technologies, Inc. | Industrials | Aerospace & Defense | $353.71 | 1,478,423 | $523M | $55.9B | 13 | 16,773 |
| LIN | Linde plc Ordinary Share | Basic Materials | Specialty Chemicals | $479.45 | 2,673,549 | $1.28B | $224.0B | 11 | 48,617 |
| LITE | Lumentum Holdings Inc. Common Stock | Technology | Communication Equipment | $607.68 | 6,171,795 | $3.75B | $34.3B | 19 | 169,192 |
| LLY | Eli Lilly & Co. | Healthcare | Drug Manufacturers - General | $997.49 | 3,121,762 | $3.11B | $685.8B | 21 | 342,935 |
| LMT | Lockheed Martin Corp. | Industrials | Aerospace & Defense | $627.88 | 1,658,009 | $1.04B | $113.5B | 14 | 96,016 |
| LOW | Lowe's Companies Inc. | Consumer Cyclical | Home Improvement Retail | $258.81 | 2,789,363 | $722M | $133.4B | 16 | 102,247 |
| LRCX | Lam Research Corp | Technology | Semiconductor Equipment & Materials | $227.92 | 11,216,285 | $2.56B | $224.7B | 15 | 480,098 |
| LVS | Las Vegas Sands Corp. | Consumer Cyclical | Resorts & Casinos | $55.97 | 4,955,610 | $277M | $36.8B | 15 | 130,485 |
| LYV | Live Nation Entertainment Inc. | Communication Services | Entertainment | $153.16 | 3,049,727 | $467M | $38.4B | 16 | 170,361 |
| MA | Mastercard Incorporated | Financial Services | Credit Services | $517.99 | 3,940,605 | $2.04B | $514.8B | 19 | 142,301 |
| MAR | Marriott International Class A Common Stock | Consumer Cyclical | Lodging | $331.79 | 1,648,104 | $547M | $71.0B | 15 | 66,891 |
| MCHP | Microchip Technology Inc | Technology | Semiconductors | $71.57 | 9,130,267 | $653M | $34.8B | 15 | 210,667 |
| MCK | McKesson Corporation | Healthcare | Medical Distribution | $897.30 | 772,430 | $693M | $101.5B | 10 | 19,792 |
| MCO | Moody's Corporation | Financial Services | Financial Data & Stock Exchanges | $462.62 | 1,367,880 | $633M | $85.6B | 7 | 11,997 |
| MDLZ | Mondelez International, Inc. Class A | Consumer Defensive | Confectioners | $58.42 | 10,704,673 | $625M | $81.0B | 13 | 105,595 |
| MDT | Medtronic plc | Healthcare | Medical Devices | $94.42 | 8,619,426 | $814M | $120.6B | 17 | 131,762 |
| MELI | Mercado Libre, Inc | Consumer Cyclical | Internet Retail | $1883.12 | 577,281 | $1.09B | $118.5B | 19 | 51,393 |
| MET | MetLife, Inc. | Financial Services | Insurance - Life | $74.04 | 3,990,238 | $295M | $55.1B | 10 | 120,544 |
| META | Meta Platforms, Inc. Class A Common Stock | Communication Services | Internet Content & Information | $634.52 | 16,358,791 | $10.38B | $1.89T | 25 | 2,806,042 |
| MLM | Martin Marietta Materials | Basic Materials | Building Materials | $634.16 | 525,407 | $333M | $38.1B | 7 | 2,879 |
| MMM | 3M Company | Industrials | Conglomerates | $157.13 | 4,189,514 | $658M | $83.5B | 15 | 102,370 |
| MNST | Monster Beverage Corporation | Consumer Defensive | Beverages - Non-Alcoholic | $78.52 | 6,170,905 | $485M | $66.3B | 8 | 62,017 |
| MO | Altria Group, Inc. | Consumer Defensive | Tobacco | $65.51 | 9,993,444 | $655M | $111.0B | 14 | 306,879 |
| MPC | MARATHON PETROLEUM CORPORATION | Energy | Oil & Gas Refining & Marketing | $209.28 | 2,598,459 | $544M | $58.6B | 11 | 75,912 |
| MPWR | Monolithic Power Systems, Inc. | Technology | Semiconductors | $1127.17 | 600,504 | $677M | $44.2B | 9 | 8,596 |
| MRK | Merck & Co., Inc. | Healthcare | Drug Manufacturers - General | $116.93 | 11,324,882 | $1.32B | $209.7B | 17 | 527,696 |
| MRVL | Marvell Technology, Inc. Common Stock | Technology | Semiconductors | $87.87 | 19,611,967 | $1.72B | $81.0B | 19 | 1,135,768 |
| MS | Morgan Stanley | Financial Services | Capital Markets | $171.65 | 7,667,224 | $1.32B | $252.7B | 19 | 394,124 |
| MSCI | MSCI, Inc. | Financial Services | Financial Data & Stock Exchanges | $559.79 | 633,901 | $355M | $43.5B | 6 | 5,114 |
| MSFT | Microsoft Corp | Technology | Software - Infrastructure | $406.02 | 36,910,868 | $14.99B | $3.61T | 24 | 3,796,408 |
| MSI | Motorola Solutions, Inc. New | Technology | Communication Equipment | $439.63 | 1,135,835 | $499M | $77.2B | 5 | 8,182 |
| MSTR | Strategy Inc Common Stock Class A | Technology | Software - Application | $138.78 | 21,738,534 | $3.02B | $101.6B | 22 | 2,468,104 |
| MTB | M&T Bank Corp. | Financial Services | Banks - Regional | $215.88 | 1,258,389 | $272M | $30.9B | 10 | 13,338 |
| MU | Micron Technology, Inc. | Technology | Semiconductors | $398.89 | 41,434,921 | $16.53B | $474.6B | 22 | 2,782,867 |
| NDAQ | Nasdaq, Inc. Common Stock | Financial Services | Financial Data & Stock Exchanges | $88.07 | 4,365,401 | $384M | $51.2B | 13 | 32,406 |
| NEE | NextEra Energy, Inc. | Utilities | Utilities - Regulated Electric | $90.46 | 9,743,901 | $881M | $156.3B | 14 | 459,883 |
| NEM | Newmont Corporation | Basic Materials | Gold | $116.31 | 10,686,647 | $1.24B | $92.7B | 16 | 530,213 |
| NFLX | NetFlix Inc | Communication Services | Entertainment | $89.37 | 48,242,352 | $4.31B | $520.4B | 20 | 5,641,440 |
| NKE | Nike, Inc. | Consumer Cyclical | Footwear & Accessories | $57.96 | 19,079,262 | $1.11B | $92.1B | 19 | 1,946,205 |
| NOC | Northrop Grumman Corp. | Industrials | Aerospace & Defense | $701.13 | 890,001 | $624M | $87.4B | 10 | 23,880 |
| NOW | SERVICENOW, INC. | Technology | Software - Application | $111.60 | 20,865,586 | $2.33B | $192.8B | 17 | 980,369 |
| NRG | NRG Energy, Inc. | Utilities | Utilities - Independent Power Producers | $157.78 | 2,599,306 | $410M | $31.6B | 13 | 41,575 |
| NSC | Norfolk Southern Corp. | Industrials | Railroads | $297.58 | 1,341,987 | $399M | $57.6B | 10 | 17,610 |
| NVDA | Nvidia Corp | Technology | Semiconductors | $182.84 | 178,557,077 | $32.65B | $4.56T | 26 | 15,535,495 |
| NXPI | NXP Semiconductors N.V. | Technology | Semiconductors | $217.25 | 2,894,519 | $629M | $57.5B | 10 | 41,416 |
| O | Realty Income Corporation | Real Estate | REIT - Retail | $63.14 | 6,456,667 | $408M | $55.6B | 8 | 130,778 |
| OKE | Oneok, Inc. | Energy | Oil & Gas Midstream | $84.11 | 5,215,023 | $439M | $51.3B | 10 | 137,755 |
| ORCL | Oracle Corp | Technology | Software - Infrastructure | $156.51 | 27,882,451 | $4.36B | $423.4B | 21 | 2,292,069 |
| ORLY | O'Reilly Automotive, Inc. | Consumer Cyclical | Auto Parts | $93.86 | 6,007,072 | $564M | $91.9B | 10 | 42,143 |
| OTIS | Otis Worldwide Corporation | Industrials | Specialty Industrial Machinery | $86.21 | 3,902,890 | $336M | $35.9B | 5 | 15,012 |
| OXY | Occidental Petroleum Corporation | Energy | Oil & Gas E&P | $52.55 | 16,696,397 | $877M | $47.4B | 18 | 1,096,369 |
| PANW | Palo Alto Networks, Inc. Common Stock | Technology | Software - Infrastructure | $165.36 | 10,854,395 | $1.79B | $125.8B | 21 | 552,141 |
| PAYX | Paychex Inc | Technology | Software - Application | $96.33 | 4,205,122 | $405M | $33.7B | 8 | 45,949 |
| PCAR | Paccar Inc | Industrials | Farm & Heavy Construction Machinery | $121.63 | 3,102,723 | $377M | $51.8B | 10 | 12,019 |
| PEG | Public Service Enterprise Group Incorporated | Utilities | Utilities - Regulated Electric | $82.36 | 2,925,927 | $241M | $41.8B | 8 | 15,866 |
| PEP | PepsiCo, Inc. | Consumer Defensive | Beverages - Non-Alcoholic | $157.63 | 7,610,427 | $1.20B | $200.8B | 17 | 332,611 |
| PFE | Pfizer Inc. | Healthcare | Drug Manufacturers - General | $26.90 | 44,678,789 | $1.20B | $135.8B | 15 | 2,476,673 |
| PG | Procter & Gamble Company | Consumer Defensive | Household & Personal Products | $151.81 | 11,314,480 | $1.72B | $347.4B | 16 | 353,293 |
| PGR | Progressive Corporation | Financial Services | Insurance - Property & Casualty | $204.39 | 3,365,390 | $688M | $145.3B | 16 | 43,577 |
| PH | Parker-Hannifin Corporation | Industrials | Specialty Industrial Machinery | $950.26 | 743,500 | $707M | $112.6B | 5 | 8,712 |
| PLD | PROLOGIS, INC. | Real Estate | REIT - Industrial | $134.41 | 3,568,577 | $480M | $109.6B | 10 | 57,283 |
| PLTR | Palantir Technologies Inc. Class A Common Stock | Technology | Software - Infrastructure | $148.62 | 51,881,436 | $7.71B | $469.0B | 20 | 3,525,282 |
| PM | Philip Morris International Inc. | Consumer Defensive | Tobacco | $173.57 | 5,290,386 | $918M | $252.7B | 16 | 140,914 |
| PNC | PNC Financial Services Group | Financial Services | Banks - Regional | $217.80 | 2,767,228 | $603M | $79.6B | 17 | 44,248 |
| PRU | Prudential Financial, Inc. | Financial Services | Insurance - Life | $101.24 | 2,392,055 | $242M | $36.6B | 10 | 81,767 |
| PSA | Public Storage | Real Estate | REIT - Industrial | $288.69 | 1,241,429 | $358M | $51.6B | 5 | 7,820 |
| PSX | PHILLIPS 66 | Energy | Oil & Gas Refining & Marketing | $160.34 | 3,116,360 | $500M | $48.7B | 17 | 73,513 |
| PWR | Quanta Services, Inc. | Industrials | Engineering & Construction | $531.71 | 1,129,555 | $601M | $62.8B | 11 | 32,475 |
| PYPL | PayPal Holdings, Inc. Common Stock | Financial Services | Credit Services | $46.78 | 23,696,969 | $1.11B | $64.4B | 18 | 1,986,603 |
| QCOM | Qualcomm Inc | Technology | Semiconductors | $140.02 | 11,383,999 | $1.59B | $188.6B | 18 | 533,346 |
| RCL | Royal Caribbean Group | Consumer Cyclical | Travel Services | $295.13 | 2,565,795 | $757M | $88.7B | 14 | 123,196 |
| REGN | Regeneron Pharmaceuticals Inc | Healthcare | Biotechnology | $763.04 | 723,134 | $552M | $60.3B | 17 | 38,188 |
| RJF | Raymond James Financial, Inc. | Financial Services | Asset Management | $155.90 | 1,402,137 | $219M | $32.3B | 7 | 7,313 |
| RMD | ResMed Inc. | Healthcare | Medical Instruments & Supplies | $246.26 | 1,104,290 | $272M | $35.3B | 6 | 13,696 |
| ROK | Rockwell Automation, Inc. | Industrials | Specialty Industrial Machinery | $391.56 | 1,012,909 | $397M | $43.9B | 7 | 23,986 |
| ROP | Roper Technologies, Inc. Common Stock | Technology | Software - Application | $359.67 | 1,716,170 | $617M | $54.1B | 5 | 7,288 |
| ROST | Ross Stores Inc | Consumer Cyclical | Apparel Retail | $203.29 | 2,632,141 | $535M | $44.5B | 15 | 29,201 |
| RSG | Republic Services Inc. | Industrials | Waste Management | $220.16 | 1,454,980 | $320M | $71.6B | 5 | 6,518 |
| RTX | RTX Corporation | Industrials | Aerospace & Defense | $200.07 | 5,951,180 | $1.19B | $227.3B | 15 | 268,064 |
| SBUX | Starbucks Corp | Consumer Cyclical | Restaurants | $95.41 | 9,051,637 | $864M | $97.2B | 17 | 513,543 |
| SCCO | Southern Copper Corporation | Basic Materials | Copper | $188.00 | 2,107,576 | $396M | $99.8B | 13 | 52,312 |
| SCHW | The Charles Schwab Corporation | Financial Services | Capital Markets | $97.20 | 10,811,746 | $1.05B | $172.9B | 18 | 453,899 |
| SHOP | Shopify Inc. Class A subordinate voting shares | Technology | Software - Application | $125.59 | 11,982,740 | $1.50B | $195.1B | 20 | 691,272 |
| SHW | The Sherwin-Williams Company | Basic Materials | Specialty Chemicals | $342.44 | 1,794,727 | $615M | $86.2B | 8 | 20,440 |
| SLB | SLB Limited | Energy | Oil & Gas Equipment & Services | $49.42 | 19,965,887 | $987M | $51.1B | 16 | 807,041 |
| SNDK | Sandisk Corporation Common Stock | Technology | Computer Hardware | $618.88 | 19,568,064 | $12.11B | $42.9B | 19 | 646,948 |
| SNOW | Snowflake Inc. | Technology | Software - Application | $175.14 | 6,746,571 | $1.18B | $93.4B | 21 | 540,127 |
| SNPS | Synopsys Inc | Technology | Software - Infrastructure | $438.91 | 2,164,774 | $950M | $88.7B | 15 | 73,243 |
| SO | The Southern Company | Utilities | Utilities - Regulated Electric | $93.71 | 6,113,141 | $573M | $105.2B | 15 | 102,608 |
| SPG | Simon Property Group, Inc. | Real Estate | REIT - Retail | $191.82 | 1,719,191 | $330M | $61.3B | 10 | 48,576 |
| SPGI | S&P Global Inc. | Financial Services | Financial Data & Stock Exchanges | $451.55 | 2,637,673 | $1.19B | $148.2B | 18 | 41,804 |
| SRE | Sempra | Utilities | Utilities - Diversified | $92.76 | 3,962,412 | $368M | $58.8B | 7 | 15,967 |
| STT | State Street Corporation | Financial Services | Asset Management | $128.20 | 2,143,747 | $275M | $33.4B | 10 | 24,304 |
| STX | Seagate Technology Holdings PLC Ordinary Shares (Ireland) | Technology | Computer Hardware | $402.21 | 4,159,033 | $1.67B | $65.6B | 15 | 169,188 |
| SYK | Stryker Corporation | Healthcare | Medical Devices | $355.88 | 2,072,528 | $738M | $143.0B | 8 | 26,799 |
| SYY | Sysco Corporation | Consumer Defensive | Food Distribution | $82.51 | 4,777,269 | $394M | $35.7B | 10 | 97,596 |
| T | AT&T Inc. | Communication Services | Telecom Services | $27.09 | 45,152,589 | $1.22B | $202.5B | 16 | 1,015,285 |
| TDG | TransDigm Group Incorporated | Industrials | Aerospace & Defense | $1288.65 | 388,185 | $500M | $76.2B | 7 | 4,633 |
| TEAM | Atlassian Corporation Class A Common Stock | Technology | Software - Application | $87.95 | 6,761,068 | $595M | $42.8B | 15 | 176,753 |
| TEL | TE Connectivity plc | Technology | Electronic Components | $219.33 | 2,255,110 | $495M | $69.0B | 9 | 34,050 |
| TFC | Truist Financial Corporation | Financial Services | Banks - Regional | $49.18 | 10,229,756 | $503M | $59.3B | 10 | 170,021 |
| TGT | Target Corporation | Consumer Defensive | Discount Stores | $114.82 | 6,187,623 | $710M | $42.2B | 19 | 480,993 |
| TJX | TJX Companies, Inc. (The) | Consumer Cyclical | Apparel Retail | $156.46 | 5,152,369 | $806M | $157.8B | 15 | 131,821 |
| TKO | TKO Group Holdings, Inc. | Communication Services | Entertainment | $203.87 | 1,181,251 | $241M | $40.2B | 7 | 18,252 |
| TMO | Thermo Fisher Scientific, Inc. | Healthcare | Diagnostics & Research | $529.04 | 2,280,476 | $1.21B | $175.5B | 13 | 48,053 |
| TMUS | T-Mobile US, Inc. | Communication Services | Telecom Services | $205.24 | 6,326,220 | $1.30B | $269.7B | 18 | 126,582 |
| TRGP | Targa Resources Corp. | Energy | Oil & Gas Midstream | $224.76 | 1,502,317 | $338M | $36.2B | 8 | 17,403 |
| TRV | The Travelers Companies, Inc. | Financial Services | Insurance - Property & Casualty | $294.52 | 1,585,961 | $467M | $63.5B | 9 | 9,352 |
| TSCO | Tractor Supply Co | Consumer Cyclical | Specialty Retail | $50.22 | 6,639,269 | $333M | $30.1B | 15 | 43,968 |
| TSLA | Tesla, Inc. Common Stock | Consumer Cyclical | Auto Manufacturers | $401.24 | 61,494,168 | $24.67B | $1.57T | 24 | 6,744,966 |
| TT | Trane Technologies plc | Industrials | Building Products & Equipment | $431.78 | 1,515,153 | $654M | $94.7B | 7 | 9,808 |
| TXN | Texas Instruments Incorporated | Technology | Semiconductors | $204.77 | 7,461,020 | $1.53B | $189.3B | 16 | 165,887 |
| UAL | United Airlines Holdings, Inc. Common Stock | Industrials | Airlines | $102.17 | 7,405,544 | $757M | $31.5B | 14 | 508,501 |
| UBER | Uber Technologies, Inc. | Technology | Software - Application | $75.43 | 19,652,066 | $1.48B | $208.1B | 20 | 1,237,215 |
| UNH | UNITEDHEALTH GROUP INCORPORATED (Delaware) | Healthcare | Healthcare Plans | $292.52 | 10,006,639 | $2.93B | $313.5B | 20 | 1,300,557 |
| UNP | Union Pacific Corp. | Industrials | Railroads | $246.90 | 3,378,690 | $834M | $140.2B | 18 | 95,498 |
| UPS | United Parcel Service, Inc. Class B | Industrials | Integrated Freight & Logistics | $106.48 | 6,490,326 | $691M | $70.8B | 15 | 419,883 |
| URI | United Rentals, Inc. | Industrials | Rental & Leasing Services | $821.56 | 658,045 | $541M | $61.4B | 13 | 25,169 |
| USB | U.S. Bancorp | Financial Services | Banks - Regional | $54.89 | 11,058,284 | $607M | $75.2B | 16 | 202,943 |
| VICI | VICI Properties Inc. Common Stock | Real Estate | REIT - Diversified | $28.61 | 9,476,918 | $271M | $34.8B | 8 | 53,965 |
| VLO | Valero Energy Corporation | Energy | Oil & Gas Refining & Marketing | $213.70 | 3,704,124 | $792M | $52.6B | 15 | 121,559 |
| VMC | Vulcan Materials Company(Holding Company) | Basic Materials | Building Materials | $292.64 | 1,297,821 | $380M | $40.9B | 4 | 8,085 |
| VRSK | Verisk Analytics, Inc. Common Stock | Industrials | Consulting Services | $197.37 | 2,097,263 | $414M | $43.7B | 5 | 19,579 |
| VRT | Vertiv Holdings Co Class A Common Stock | Industrials | Electrical Equipment & Parts | $234.77 | 7,636,603 | $1.79B | $59.0B | 15 | 413,218 |
| VRTX | Vertex Pharmaceuticals Inc | Healthcare | Biotechnology | $463.15 | 1,460,057 | $676M | $100.9B | 16 | 46,809 |
| VST | Vistra Corp. | Utilities | Utilities - Independent Power Producers | $160.70 | 5,089,158 | $818M | $67.6B | 18 | 326,888 |
| VTR | Ventas, Inc. | Real Estate | REIT - Healthcare Facilities | $82.78 | 3,093,042 | $256M | $32.4B | 7 | 11,421 |
| VZ | Verizon Communications | Communication Services | Telecom Services | $47.24 | 31,539,664 | $1.49B | $182.9B | 17 | 1,082,996 |
| WAB | Wabtec Inc. | Industrials | Railroads | $246.79 | 911,532 | $225M | $34.3B | 5 | 2,459 |
| WBD | Warner Bros. Discovery, Inc. Series A Common Stock | Communication Services | Entertainment | $27.86 | 25,673,121 | $715M | $48.4B | 19 | 1,740,658 |
| WDAY | Workday, Inc. Class A Common Stock | Technology | Software - Application | $148.46 | 5,450,578 | $809M | $64.4B | 14 | 157,586 |
| WDC | Western Digital Corp. | Technology | Computer Hardware | $275.94 | 9,566,795 | $2.64B | $71.5B | 19 | 380,098 |
| WEC | WEC Energy Group, Inc. | Utilities | Utilities - Regulated Electric | $113.76 | 2,231,803 | $254M | $37.3B | 6 | 9,393 |
| WELL | Welltower Inc. | Real Estate | REIT - Healthcare Facilities | $199.71 | 3,200,948 | $639M | $122.1B | 7 | 21,219 |
| WFC | Wells Fargo & Co. | Financial Services | Banks - Diversified | $84.49 | 17,335,008 | $1.46B | $270.2B | 20 | 1,151,074 |
| WM | Waste Management, Inc. | Industrials | Waste Management | $231.36 | 2,245,108 | $519M | $89.3B | 10 | 36,165 |
| WMB | Williams Companies Inc. | Energy | Oil & Gas Midstream | $70.66 | 7,197,614 | $509M | $77.6B | 17 | 163,138 |
| WMT | Walmart Inc. Common Stock | Consumer Defensive | Discount Stores | $124.17 | 29,917,692 | $3.71B | $810.6B | 17 | 1,040,746 |
| WRB | W.R. Berkley Corporation | Financial Services | Insurance - Property & Casualty | $68.49 | 2,235,857 | $153M | $30.7B | 5 | 5,640 |
| WTW | Willis Towers Watson Public Limited Company Ordinary Shares | Financial Services | Insurance Brokers | $301.52 | 794,326 | $240M | $33.9B | 4 | 2,192 |
| XEL | Xcel Energy, Inc. | Utilities | Utilities - Regulated Electric | $79.27 | 4,835,386 | $383M | $48.0B | 8 | 11,315 |
| XYL | Xylem Inc | Industrials | Specialty Industrial Machinery | $129.51 | 2,019,902 | $262M | $36.0B | 6 | 18,275 |
| YUM | Yum! Brands, Inc. | Consumer Cyclical | Restaurants | $159.04 | 1,896,853 | $302M | $42.7B | 11 | 19,099 |
| ZS | Zscaler, Inc. Common Stock | Technology | Software - Infrastructure | $166.54 | 2,907,133 | $484M | $31.9B | 18 | 177,986 |
| ZTS | ZOETIS INC. | Healthcare | Drug Manufacturers - Specialty & Generic | $122.61 | 4,255,098 | $522M | $64.8B | 10 | 63,781 |
