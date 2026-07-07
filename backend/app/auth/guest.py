"""游客（guest）会话语义（AUTH_GUEST_ENABLED，仅 standalone/cloud 可开）。

设计取舍（选最简且权限模型自洽的路径）：

- 游客是**共享的只读本地账号**：`external_provider="guest"`、`external_id="guest"`、
  全局角色复用 viewer、无密码（password_hash 为空，无法走密码登录，也不可改密）。
- 游客**不持有任何 workspace membership**：共享账号一旦写 membership，多个游客
  会互相订阅/退订、出现在成员列表里、甚至可能被管理员误升权。取而代之的是
  **隐式只读可见性**：游客对所有 enabled 且 `visibility=internal_public` 的工作台
  按 viewer 视角浏览（见 `assert_workspace_member` 与 workspaces 列表的 guest 分支），
  private 工作台对游客完全不可见。
- 游客**禁止一切写操作**（评论/点赞/订阅等全部 403，文案提示注册后可用）。
  该门禁集中在 `get_current_user`（所有登录态端点的唯一入口依赖），不散落 if；
  仅豁免 `/api/auth/logout`。订阅 internal_public 工作台请注册正式账号后再操作。
- 关闭 AUTH_GUEST_ENABLED 后，存量游客会话立即失效（get_current_user 按未登录处理）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.identity import Role, User

GUEST_PROVIDER = "guest"
GUEST_EXTERNAL_ID = "guest"
GUEST_DISPLAY_NAME = "游客"
GUEST_GLOBAL_ROLE = "viewer"
# 游客唯一放行的写路径：退出登录。
GUEST_ALLOWED_WRITE_PATHS = {"/api/auth/logout"}
GUEST_READ_ONLY_DETAIL = "guest_read_only: 游客账号为只读模式，注册或登录正式账号后即可评论、点赞与订阅工作台"


def is_guest_user(user: User) -> bool:
    return user.external_provider == GUEST_PROVIDER


def find_guest_user(session: Session) -> User | None:
    return session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(
            User.external_provider == GUEST_PROVIDER,
            User.external_id == GUEST_EXTERNAL_ID,
        ),
    )


def ensure_guest_user(session: Session) -> User:
    """取共享 guest 用户，不存在则创建（幂等；调用方负责 commit）。"""
    user = find_guest_user(session)
    if user is not None:
        if not user.is_active or user.status != "active":
            # 共享游客账号不走停用流程：开关关掉即全体游客下线。
            user.is_active = True
            user.status = "active"
        return user
    role = session.scalar(select(Role).where(Role.code == GUEST_GLOBAL_ROLE))
    if role is None:
        raise ValueError(f"Guest login requires the {GUEST_GLOBAL_ROLE} role to be seeded")
    user = User(
        external_provider=GUEST_PROVIDER,
        external_id=GUEST_EXTERNAL_ID,
        username=_unique_guest_username(session),
        display_name=GUEST_DISPLAY_NAME,
        password_hash=None,
        status="active",
        roles=[role],
    )
    session.add(user)
    session.flush()
    return user


def _unique_guest_username(session: Session) -> str:
    candidate = "guest"
    suffix = 2
    while session.scalar(select(User.id).where(User.username == candidate)) is not None:
        candidate = f"guest_{suffix}"
        suffix += 1
    return candidate
