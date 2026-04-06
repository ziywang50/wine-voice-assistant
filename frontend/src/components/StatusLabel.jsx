const LABELS = {
  idle: 'Tap to speak',
  recording: 'Listening… tap to stop',
  transcribing: 'Transcribing…',
  thinking: 'Thinking…',
  speaking: 'Playing response…',
  error: 'Something went wrong',
}

export default function StatusLabel({ status }) {
  return (
    <p className={`status-label status-label--${status}`} aria-live="polite">
      {LABELS[status] ?? 'Tap to speak'}
    </p>
  )
}
