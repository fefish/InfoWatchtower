from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user
from app.auth.service import user_to_read, write_audit
from app.core.database import get_db_session
from app.models.identity import User, UserGroup, UserGroupMember
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.groups import (
    UserGroupCreate,
    UserGroupDetailRead,
    UserGroupMemberAdd,
    UserGroupRead,
    UserGroupUpdate,
    WorkspaceMembersBulkAdd,
    WorkspaceMembersBulkAddRead,
)

router = APIRouter(prefix="/api", tags=["user-groups"])

# 组 CRUD 与组成员维护的权限门：实例级管理者。组本身不构成第三层权限，
# 只用于批量把成员加入工作台（workspace membership 仍是权限事实源）。
GROUP_MANAGER_ROLES = {"super_admin", "editor_admin"}


def require_group_manager(current_user: User = Depends(get_current_user)) -> User:
    if {role.code for role in current_user.roles}.isdisjoint(GROUP_MANAGER_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires super_admin or editor_admin",
        )
    return current_user


GROUP_MANAGER = Depends(require_group_manager)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.get("/user-groups", response_model=list[UserGroupRead])
def list_user_groups(
    _: User = GROUP_MANAGER,
    session: Session = DB_SESSION,
) -> list[UserGroupRead]:
    member_counts = dict(
        session.execute(
            select(UserGroupMember.group_id, func.count(UserGroupMember.id)).group_by(
                UserGroupMember.group_id,
            ),
        ).all(),
    )
    groups = session.scalars(select(UserGroup).order_by(UserGroup.code)).all()
    return [_group_to_read(group, member_counts.get(group.id, 0)) for group in groups]


@router.post("/user-groups", response_model=UserGroupRead, status_code=status.HTTP_201_CREATED)
def create_user_group(
    payload: UserGroupCreate,
    current_user: User = GROUP_MANAGER,
    session: Session = DB_SESSION,
) -> UserGroupRead:
    existing = session.scalar(select(UserGroup).where(UserGroup.code == payload.code))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User group code already exists: {payload.code}",
        )
    group = UserGroup(
        code=payload.code,
        name=payload.name.strip(),
        description=payload.description.strip(),
    )
    session.add(group)
    session.flush()
    write_audit(
        session,
        current_user,
        "user_group.create",
        "user_group",
        group.id,
        {"code": group.code, "name": group.name},
    )
    session.commit()
    return _group_to_read(group, 0)


@router.get("/user-groups/{group_code}", response_model=UserGroupDetailRead)
def get_user_group(
    group_code: str,
    _: User = GROUP_MANAGER,
    session: Session = DB_SESSION,
) -> UserGroupDetailRead:
    group = _load_group(session, group_code)
    return _group_to_detail_read(session, group)


@router.patch("/user-groups/{group_code}", response_model=UserGroupDetailRead)
def update_user_group(
    group_code: str,
    payload: UserGroupUpdate,
    current_user: User = GROUP_MANAGER,
    session: Session = DB_SESSION,
) -> UserGroupDetailRead:
    group = _load_group(session, group_code)
    changes: dict[str, str] = {}
    if payload.name is not None:
        group.name = payload.name.strip()
        changes["name"] = group.name
    if payload.description is not None:
        group.description = payload.description.strip()
        changes["description"] = group.description
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No group fields provided")
    write_audit(
        session,
        current_user,
        "user_group.update",
        "user_group",
        group.id,
        {"code": group.code, **changes},
    )
    session.commit()
    return _group_to_detail_read(session, group)


@router.delete("/user-groups/{group_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_group(
    group_code: str,
    current_user: User = GROUP_MANAGER,
    session: Session = DB_SESSION,
) -> Response:
    group = _load_group(session, group_code)
    write_audit(
        session,
        current_user,
        "user_group.delete",
        "user_group",
        group.id,
        {"code": group.code, "name": group.name},
    )
    session.delete(group)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/user-groups/{group_code}/members", response_model=UserGroupDetailRead)
def add_user_group_member(
    group_code: str,
    payload: UserGroupMemberAdd,
    current_user: User = GROUP_MANAGER,
    session: Session = DB_SESSION,
) -> UserGroupDetailRead:
    group = _load_group(session, group_code)
    target_user = session.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    membership = session.scalar(
        select(UserGroupMember).where(
            UserGroupMember.group_id == group.id,
            UserGroupMember.user_id == target_user.id,
        ),
    )
    if membership is None:
        session.add(UserGroupMember(group_id=group.id, user_id=target_user.id))
        session.flush()
        write_audit(
            session,
            current_user,
            "user_group.member.add",
            "user_group",
            group.id,
            {"code": group.code, "user_id": target_user.id, "username": target_user.username},
        )
        session.commit()
    return _group_to_detail_read(session, group)


@router.delete("/user-groups/{group_code}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user_group_member(
    group_code: str,
    user_id: str,
    current_user: User = GROUP_MANAGER,
    session: Session = DB_SESSION,
) -> Response:
    group = _load_group(session, group_code)
    membership = session.scalar(
        select(UserGroupMember).where(
            UserGroupMember.group_id == group.id,
            UserGroupMember.user_id == user_id,
        ),
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group member not found")
    session.delete(membership)
    write_audit(
        session,
        current_user,
        "user_group.member.remove",
        "user_group",
        group.id,
        {"code": group.code, "user_id": user_id},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workspaces/{workspace_code}/members/bulk", response_model=WorkspaceMembersBulkAddRead)
def bulk_add_workspace_members_by_group(
    workspace_code: str,
    payload: WorkspaceMembersBulkAdd,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> WorkspaceMembersBulkAddRead:
    """按组批量把成员加入工作台：展开为逐用户 membership，幂等。

    已存在且启用的 membership 保持原角色（不升级、不降级，尤其不动 owner）；
    停用的 membership 以本次角色重新启用；停用账号跳过。
    """

    workspace = session.scalar(
        select(Workspace).where(Workspace.code == workspace_code, Workspace.enabled.is_(True)),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    group = _load_group(session, payload.group_code)

    group_members = session.scalars(
        select(UserGroupMember)
        .options(selectinload(UserGroupMember.user))
        .where(UserGroupMember.group_id == group.id),
    ).all()
    memberships_by_user_id = {
        membership.user_id: membership
        for membership in session.scalars(
            select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id),
        ).all()
    }

    added_user_ids: list[str] = []
    reactivated_user_ids: list[str] = []
    skipped_user_ids: list[str] = []
    for group_member in group_members:
        user = group_member.user
        if user is None or not user.is_active or user.status not in {"active", "must_change_password"}:
            skipped_user_ids.append(group_member.user_id)
            continue
        membership = memberships_by_user_id.get(user.id)
        if membership is None:
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    workspace_role=payload.workspace_role,
                    enabled=True,
                ),
            )
            added_user_ids.append(user.id)
        elif not membership.enabled:
            membership.enabled = True
            membership.workspace_role = payload.workspace_role
            reactivated_user_ids.append(user.id)
        else:
            skipped_user_ids.append(user.id)

    write_audit(
        session,
        current_user,
        "workspace.member.bulk_upsert",
        "workspace",
        workspace.id,
        {
            "workspace_code": workspace.code,
            "group_code": group.code,
            "workspace_role": payload.workspace_role,
            "added_user_ids": sorted(added_user_ids),
            "reactivated_user_ids": sorted(reactivated_user_ids),
            "skipped_user_ids": sorted(skipped_user_ids),
        },
    )
    session.commit()
    member_count = session.scalar(
        select(func.count(WorkspaceMembership.id)).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    return WorkspaceMembersBulkAddRead(
        workspace_code=workspace.code,
        group_code=group.code,
        workspace_role=payload.workspace_role,
        added_count=len(added_user_ids),
        reactivated_count=len(reactivated_user_ids),
        skipped_count=len(skipped_user_ids),
        member_count=int(member_count or 0),
    )


def _load_group(session: Session, group_code: str) -> UserGroup:
    group = session.scalar(select(UserGroup).where(UserGroup.code == group_code))
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User group not found")
    return group


def _group_to_read(group: UserGroup, member_count: int) -> UserGroupRead:
    return UserGroupRead(
        id=group.id,
        code=group.code,
        name=group.name,
        description=group.description,
        member_count=member_count,
    )


def _group_to_detail_read(session: Session, group: UserGroup) -> UserGroupDetailRead:
    members = session.scalars(
        select(User)
        .join(UserGroupMember, UserGroupMember.user_id == User.id)
        .options(selectinload(User.roles))
        .where(UserGroupMember.group_id == group.id)
        .order_by(User.username),
    ).all()
    return UserGroupDetailRead(
        id=group.id,
        code=group.code,
        name=group.name,
        description=group.description,
        member_count=len(members),
        members=[user_to_read(user) for user in members],
    )
