"""
сид: каталог товаров, остатки, пулы кодов поставщиков и их конфиг.
Данные — из материалов задания.
"""

from yoyo import step

__depends__ = {"20250715_01_geLIi-initial"}

PRODUCTS = [
    ("STEAM-TOPUP-500",  "Пополнение Steam 500 ₽",        "topup",        500,  "assets/steam.png"),
    ("STEAM-TOPUP-1000", "Пополнение Steam 1000 ₽",       "topup",        1000, "assets/steam.png"),
    ("STEAM-TOPUP-2500", "Пополнение Steam 2500 ₽",       "topup",        2500, "assets/steam.png"),
    ("KEY-CS2-PRIME",    "CS2 Prime Status ключ",         "key",          1290, "assets/cs2.png"),
    ("KEY-GTA5",         "GTA V ключ активации",          "key",          1990, "assets/gta5.png"),
    ("KEY-EFT",          "Escape from Tarkov ключ",       "key",          3490, "assets/eft.png"),
    ("SUB-DISCORD-1M",   "Discord Nitro 1 месяц",         "subscription", 399,  "assets/discord.png"),
    ("SUB-YT-3M",        "YouTube Premium 3 месяца",      "subscription", 1490, "assets/youtube.png"),
    ("SUB-SPOTIFY-1M",   "Spotify Premium 1 месяц",       "subscription", 299,  "assets/spotify.png"),
    ("GIFT-PSN-1000",    "PlayStation Store карта 1000 ₽","giftcard",     1000, "assets/psn.png"),
    ("GIFT-XBOX-1500",   "Xbox Gift Card 1500 ₽",         "giftcard",     1500, "assets/xbox.png"),
    ("GIFT-ROBLOX-800",  "Roblox 800 Robux",              "giftcard",     890,  "assets/roblox.png"),
]

KEYS = [
    "LFXC-TNCS-BPCD","P3EI-W8UO-9B4K","FEL3-GUXN-TCCH","YPLV-QK2Z-IUS5","0K9E-P1FR-BY1U",
    "5LZV-UQ48-RXCZ","X93K-NYAQ-GEC1","EIO5-CQT5-35KO","M58F-GIIR-VJAP","NU8Y-SWYB-6252",
    "OODW-CCHF-MBAF","DNA5-WFJM-NE49","QRDD-MJ3F-A8TF","TAT9-5ZJN-G1T2","LI39-4330-ISMB",
    "BKJY-8Q79-8NHI","HHW6-4RX2-DX62","1RG2-L28O-O80G","EF63-F39X-MTEA","8XS7-P53H-JKIV",
    "JPE6-MQV6-P7ST","SAPG-A2GR-0ULS","T2DU-IJ1S-U16P","WSSY-QTR7-Z57J","U74E-EPCI-CY26",
    "FZXF-58H8-OR93","FPSM-HLZA-TPAL","WSC9-28DJ-B2JE","P63J-F7UZ-DCYP","C7W2-D4C5-QMT7",
    "JESI-DFBH-LK1K","SGMA-JA0T-GR7D","3PR4-OSY9-M3ZW","OMBE-C0JF-D45Y","KIKQ-FQJ8-9TI8",
    "LMAN-RSHS-AJDO","BAKI-VT1X-Z5OL","9F0X-B46W-03FS","S423-V6YY-IBEM","D4UW-WYRA-20ST",
    "XC0J-CJ0H-09RN","RY1W-XCFJ-0KUA","CJYY-YKSQ-QE6H","97AQ-38QJ-H8HU","FS8E-3S5Z-I6RA",
    "ARQK-FML4-A14E","7Z6K-NO9V-MPJB","D4K7-IJSG-N853","W67T-ZB0Q-1XKB","7EQM-K09J-XKUO",
]


def apply_step(conn):
    cur = conn.cursor()
    for sku, name, ptype, price, image in PRODUCTS:
        cur.execute(
            "INSERT INTO products (sku, name, type, price, image) VALUES (%s,%s,%s,%s,%s)",
            (sku, name, ptype, price, image),
        )
        # Storefront stock is a denormalized projection; seed a demo quantity.
        # GIFT-ROBLOX-800 is seeded empty to demonstrate the out_of_stock storefront state.
        available = 0 if sku == "GIFT-ROBLOX-800" else 25
        cur.execute(
            "INSERT INTO stock (sku, available) VALUES (%s,%s)", (sku, available)
        )

    # Split the 50-key pool between the two suppliers: A gets first 25, B the rest.
    for i, code in enumerate(KEYS):
        supplier = "A" if i < 25 else "B"
        cur.execute(
            "INSERT INTO supplier_inventory (supplier, code) VALUES (%s,%s)",
            (supplier, code),
        )

    for supplier in ("A", "B"):
        cur.execute(
            "INSERT INTO supplier_config (supplier) VALUES (%s)", (supplier,)
        )


def rollback_step(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM supplier_config")
    cur.execute("DELETE FROM supplier_inventory")
    cur.execute("DELETE FROM stock")
    cur.execute("DELETE FROM products")


steps = [step(apply_step, rollback_step)]