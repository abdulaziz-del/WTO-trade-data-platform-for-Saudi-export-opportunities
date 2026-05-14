from typing import List
from fastapi import Depends

class CurrentUser:
    def __init__(self):
        self.id = "local-user"
        self.email = "local@example.com"
        self.roles = ["ADMIN", "ANALYST"]

def require_role(required_roles: List[str]):
    async def role_checker():
        return CurrentUser()
    return role_checker
