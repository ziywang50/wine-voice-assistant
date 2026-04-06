export default function MicButton({ status, onClick, onCancel }) {
  const isRecording = status === 'recording'
  const isBusy = status === 'transcribing' || status === 'thinking'
  const isSpeaking = status === 'speaking'
  const isCancelable = isBusy || isSpeaking
  const isDisabled = isCancelable

  return (
    <div className={`mic-wrapper ${status}`}>
      <button
        className={`mic-btn ${status}`}
        onClick={onClick}
        disabled={isDisabled}
        aria-label={isRecording ? 'Stop recording' : 'Start recording'}
      >
        {/* Idle / error: mic icon */}
        {(status === 'idle' || status === 'error') && (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
        )}

        {/* Recording: stop (square) icon */}
        {isRecording && (
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <rect x="5" y="5" width="14" height="14" rx="2" />
          </svg>
        )}

        {/* Busy: spinner */}
        {isBusy && (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
               className="spinner" aria-hidden="true">
            <circle cx="12" cy="12" r="9" strokeOpacity="0.2" />
            <path d="M12 3a9 9 0 0 1 9 9" />
          </svg>
        )}

        {/* Speaking: speaker icon */}
        {isSpeaking && (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
            <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
          </svg>
        )}
      </button>

      {isCancelable && (
        <button
          className="cancel-btn"
          onClick={onCancel}
          aria-label="Cancel"
        >
          ✕
        </button>
      )}
    </div>
  )
}
