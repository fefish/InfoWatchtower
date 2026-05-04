# 私有参考资料

主仓后续可能公开，因此完整旧系统参考资料不提交到本仓。

完整参考资料放在私有仓：

```text
git@github.com:fefish/InfoWatchtower-References.git
```

本地使用时，把私有仓克隆到本目录：

```bash
git clone git@github.com:fefish/InfoWatchtower-References.git references/private
```

或者保持兼容旧路径：

```bash
git clone git@github.com:fefish/InfoWatchtower-References.git /tmp/infowatchtower-references
ln -s /tmp/infowatchtower-references/legacy-auto-sync-20260412 references/legacy-auto-sync-20260412
```

约定：

- `references/legacy-auto-sync-20260412/` 是本地私有资料路径，不进主仓。
- `references/private/` 是本地私有参考仓克隆路径，不进主仓。
- 主仓只保留公开安全的设计、代码、契约和种子配置。
- 后续 AI 如果需要旧系统样本，应使用有权限的 token/SSH key 拉取私有参考仓。

