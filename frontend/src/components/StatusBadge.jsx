export function StatusBadge({ status, isStreaming }) {
  const value = status ?? (isStreaming ? "running" : "idle");
  const labelByStatus = {
    idle: "대기",
    queued: "대기열",
    running: "실행 중",
    waiting: "사용자 입력 대기",
    completed: "완료",
    failed: "실패",
  };

  return <span className={`status ${value}`}>{labelByStatus[value] ?? value}</span>;
}
