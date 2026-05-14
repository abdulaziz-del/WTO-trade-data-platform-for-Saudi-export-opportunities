from dataclasses import dataclass
from typing import List

@dataclass
class User:
    id: str = "local-user"
    email: str = "local@example.com"
    roles: List[str] = None
