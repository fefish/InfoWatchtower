/**
 * 工作台级调度策略与调度心跳 API（pipeline-jobs-design §8.2/§8.5，WP3-H）。
 *
 * - GET/PATCH /api/workspaces/{code}/schedule-policy：策略读写（读返回策略 +
 *   resolved 生效值 + next_run_at 预览 + 实例基线，供「自动化」卡标注生效值来源）；
 * - GET /api/pipeline/scheduler/status：心跳与下次运行（只读 DB，不与 scheduler
 *   进程通信；heartbeat_stale=true 或查询失败一律渲染离线/隐藏，不得假在线）。
 */
import { requestJson } from "./http";

export interface SchedulePolicyRetry {
  max_attempts: number;
  backoff_seconds: number;
}

export interface SchedulePolicyWeekly {
  enabled: boolean;
  weekly_day: number;
  weekly_time: string;
}

/** 工作台存储的策略文档：null 字段=跟随实例基线（§8.2 字段规格）。 */
export interface SchedulePolicyDocument {
  enabled: boolean | null;
  daily_time: string | null;
  day_offset: number | null;
  source_types: string[] | null;
  retry: SchedulePolicyRetry;
  weekly: SchedulePolicyWeekly;
}

export interface ResolvedScheduleRecord {
  effective_enabled: boolean;
  effective_daily_time: string | null;
  effective_day_offset: number;
  effective_source_types: string[];
  // workspace（本工作台策略生效）| instance（全部跟随实例基线）
  policy_source: string;
  next_run_at: string | null;
  retry: SchedulePolicyRetry;
  weekly: SchedulePolicyWeekly;
}

export interface ScheduleInstanceBaselineRecord {
  scheduler_enabled: boolean;
  daily_time: string | null;
  timezone: string;
  day_offset: number;
  source_types: string[];
  workspace_code: string;
}

export interface WorkspaceSchedulePolicyRecord {
  workspace_code: string;
  policy: SchedulePolicyDocument;
  resolved: ResolvedScheduleRecord;
  instance: ScheduleInstanceBaselineRecord;
}

/** PATCH body：全量策略文档（缺省字段回落契约默认，因此保存时必须回传未编辑字段）。 */
export interface WorkspaceSchedulePolicyUpdate {
  enabled: boolean | null;
  daily_time: string | null;
  day_offset: number | null;
  source_types: string[] | null;
  retry: SchedulePolicyRetry;
  weekly: SchedulePolicyWeekly;
}

export async function fetchWorkspaceSchedulePolicy(
  workspaceCode: string
): Promise<WorkspaceSchedulePolicyRecord> {
  return requestJson<WorkspaceSchedulePolicyRecord>(`/api/workspaces/${workspaceCode}/schedule-policy`);
}

export async function updateWorkspaceSchedulePolicy(
  workspaceCode: string,
  payload: WorkspaceSchedulePolicyUpdate
): Promise<WorkspaceSchedulePolicyRecord> {
  return requestJson<WorkspaceSchedulePolicyRecord>(`/api/workspaces/${workspaceCode}/schedule-policy`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

// --- 调度心跳（§8.5） ---

export interface SchedulerStatusRunRecord {
  run_id: string;
  day_key: string;
  status: string;
  trigger_type: string;
  attempt: number;
  error_code: string;
  skip_reason: string;
  finished_at: string | null;
}

export interface SchedulerStatusPendingRetryRecord {
  run_id: string;
  attempt: number;
  next_attempt: number;
  next_retry_at: string | null;
  error_code: string;
}

export interface SchedulerStatusWorkspaceRecord {
  workspace_code: string;
  effective_enabled: boolean;
  effective_daily_time: string | null;
  effective_day_offset: number;
  policy_source: string;
  next_run_at: string | null;
  weekly_enabled: boolean;
  last_runs: SchedulerStatusRunRecord[];
  pending_retry: SchedulerStatusPendingRetryRecord | null;
}

export interface SchedulerStatusRecord {
  instance_enabled: boolean;
  deploy_mode: string;
  capability_ingestion: boolean;
  timezone: string;
  heartbeat_at: string | null;
  // now - max(last_tick_at) > 180s 或心跳表为空；前端据此渲染离线，不允许假在线
  heartbeat_stale: boolean;
  workspaces: SchedulerStatusWorkspaceRecord[];
}

export async function fetchSchedulerStatus(): Promise<SchedulerStatusRecord> {
  return requestJson<SchedulerStatusRecord>("/api/pipeline/scheduler/status");
}
