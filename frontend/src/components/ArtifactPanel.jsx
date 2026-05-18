export function ArtifactPanel({ artifacts }) {
  if (artifacts.length === 0) {
    return <p className="muted">생성된 artifact가 아직 없습니다.</p>;
  }

  return (
    <ul className="artifact-list">
      {artifacts.map((artifact) => (
        <li className="artifact" key={artifact.id}>
          <div className="row">
            <strong>{artifact.title}</strong>
            <span className="muted">{artifact.kind}</span>
          </div>
          {artifact.preview ? <p>{artifact.preview}</p> : null}
          {artifact.downloadUrl ? (
            <a href={artifact.downloadUrl}>열기</a>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
