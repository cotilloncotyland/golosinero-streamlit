from dataclasses import dataclass, asdict

@dataclass
class Product:
    sku: str
    name: str
    price: float
    stock: int

@dataclass
class Rule:
    sku: str
    category: str
    pack_units: int
    brand_line: str

@dataclass
class ComboItem:
    sku: str
    name: str
    category: str
    quantity: int
    pack_units: int
    unit_price: float
    stock: int
    image_url: str = ""
    flavor_group: str = ""
    editable_flavor: bool = False
    note: str = ""

    def to_dict(self):
        return asdict(self)
