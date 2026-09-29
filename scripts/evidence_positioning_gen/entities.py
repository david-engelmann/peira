"""Shared entity pools for evidence_positioning authoring. Deterministic draws."""
import random

FIRST = """Aisha Marcus Priya Deshawn Lena Kwame Sofia Raj Tomas Elena Viktor Amara
Dmitri Yuki Carlos Fatima Omar Ingrid Hassan Mei Javier Zara Kofi Nadia
Pavel Lena2""".split()
# expanded below programmatically to avoid collisions
FIRST = [
"Aisha","Marcus","Priya","Deshawn","Lena","Kwame","Sofia","Raj","Tomas","Elena",
"Viktor","Amara","Dmitri","Yuki","Carlos","Fatima","Omar","Ingrid","Hassan","Mei",
"Javier","Zara","Kofi","Nadia","Pavel","Anika","Ravi","Sven","Marta","Ibrahim",
"Tessa","Owen","Noor","Felix","Hana","Diego","Ruth","Samir","Elsa","Tariq",
"June","Oscar","Lila","Nikhil","Greta","Yusuf","Cora","Dante","Wren","Silas",
"Mira","Jasper","Alba","Ruben","Sana","Theo","Iris","Malik","Odette","Finn",
"Zola","Emmett","Nia","Rhys","Paloma","Stellan","Ines","Bodhi","Suki","Alden",
"Vera","Casper","Dahlia","Ezra","Farah","Gus","Hazel","Ivan","Jada","Kai",
"Luna","Milo","Nora","Otis","Pippa","Quinn","Rosa","Seth","Talia","Umar",
"Vince","Willa","Xander","Yara","Zane","Adele","Bram","Celia","Dorian","Elif",
"Farid","Gemma","Hugo","Ilse","Joren","Kira","Lars","Mona","Nils","Opal",
"Petra","Ramon","Selma","Tove","Ulf","Vanya","Wilma","Ximena","Yosef","Zelda",
]

LAST = [
"Okoro","Lindqvist","Sharma","Boateng","Novak","Garcia","Kim","Okafor","Silva","Rossi",
"Meyer","Haddad","Tanaka","Muller","Costa","Ali","Berg","Diallo","Chen","Novikova",
"Santos","Weber","Khan","Larsen","Petrov","Nguyen","Fischer","Adeyemi","Kowalski","Rahman",
"Dubois","Moreau","Ito","Silva2","Johansson","Osei","Bakker","Singh","Andersen","Mora",
]

ORG = [
"Meridian Labs","Bluepeak Systems","Northgate Financial","Cedar Health","Atlas Freight",
"Beacon Analytics","Cobalt Retail","Driftwell Energy","Ember Foods","Foundry Six",
"Granite Insurance","Harborlight Media","Ironclad Security","Juniper Robotics","Keystone Bank",
"Lumen Grid","Marble & Co","Nimbus Cloud","Onyx Motors","Prairie Trust",
"Quartz Mining","Ridgeline Health","Sable Ventures","Tidewater Shipping","Umbra AI",
"Vector Supply","Willow Creek Farms","Xylem Water","Yellowpine Lumber","Zenith Air",
"Copperline Telecom","Dovetail Homes","Eastward Bank","Fernway Foods","Glacier Peak Outfitters",
"Hearthstone Realty","Indigo Press","Jolt Cola","Kestrel Drones","Larkspur Hotels",
"Mesa Verde Solar","Northloop Bikes","Osprey Legal","Palisade Capital","Quarry Stone",
"Redwood Credit Union","Sagebrush Health","Timberline Gear","Union Pacific Foods","Vista Print Co",
"Waterline Marine","Xenon Chips","Yorktown Textiles","Zephyr Rail",
]

PRODUCT = [
"payment gateway","payroll suite","CRM module","analytics dashboard","mobile SDK",
"fraud filter","inventory tracker","chat widget","billing engine","SSO connector",
"data pipeline","alerting service","backup appliance","VPN concentrator","helpdesk portal",
]

AMOUNTS = ["$40K","$55K","$75K","$90K","$120K","$150K","$180K","$220K","$250K","$300K",
"$350K","$400K","$480K","$520K","$600K","$750K","$900K","$1.1M","$1.4M","$1.8M",
"$2.2M","$2.8M","$3.5M","$4.2M","$5M","$6.5M","$8M","$11M","$14M","$18M",
"$22M","$30M","$45M","$60M","$85M","$120M","$200M","$340M"]

PCTS = ["3%","5%","7%","9%","12%","15%","18%","22%","25%","28%","31%","34%","38%","41%",
"44%","47%","52%","58%","63%","68%","74%","81%","87%","93%"]

YEARS = ["2 years","3 years","4 years","5 years","6 years","7 years","8 years","10 years",
"12 years","15 years","18 years","22 years"]

MONTHS = ["3 months","6 months","9 months","14 months","18 months","2 years","30 months"]

DAYS = ["11 days","17 days","23 days","29 days","36 days","44 days","52 days","61 days","78 days"]

RATINGS = ["4.9/5","4.8/5","4.7/5","4.6/5","4.5/5","4.4/5","4.3/5","4.2/5","9.6/10","9.4/10",
"9.2/10","9.0/10","8.8/10","8.6/10"]

SCORES = ["98th percentile","95th percentile","92nd percentile","89th percentile","97th percentile",
"91st percentile","88th percentile","94th percentile"]

def draw(rng, pool, n):
    """Draw n distinct items from pool (copy to avoid mutating module list)."""
    return rng.sample(pool, n)
