"""联动同步（extranet feed 下发 / intranet 定时拉取）。

规格：docs/deployment/deployment-topology.md §3；契约：config/contracts/sync_strategy.json。
records/apply 同时被手工同步包（operations 路由）与 api_pull（本包 pull 模块）复用。
"""
