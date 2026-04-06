export default function TranscriptArea({ transcript, status }) {
  const showPlaceholder = !transcript && status === 'idle'

  return (
    <div className="transcript-area" aria-label="Your question">
      {showPlaceholder ? (
        <p className="placeholder-text">Press the mic and ask a question&hellip;</p>
      ) : (
        <p className="transcript-text">{transcript || '\u00A0'}</p>
      )}
    </div>
  )
}
