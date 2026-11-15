import bcrypt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码
    plain_password: 前端已经做过 SHA256 的密码
    hashed_password: 数据库中存储的 bcrypt 哈希
    """

    # 将两个密码都编码为 UTF-8，并使用 bcrypt.checkpw() 进行比较。如果匹配，返回 True，否则返回 False。
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    """对密码进行哈希
    password: 前端已经做过 SHA256 的密码
    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
