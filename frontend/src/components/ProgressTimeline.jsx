export function ProgressTimeline({ events }) {
  if (events.length === 0) {
    return <p className="muted">아직 수신된 진행 이벤트가 없습니다.</p>;
  }

  return (
    <ol className="event-list">
      {events.map((event) => (
        <li className="event" key={event.id}>
          <div className="row">
            <strong>{event.title}</strong>
            <span className="muted">{event.stage}</span>
          </div>
          {event.message ? <p>{event.message}</p> : null}
        </li>
      ))}
    </ol>
  );
}
