export default function AnswerArea({ answer, error, status, onRetry }) {
  if (!answer && !error) return null

  return (
    <div className="answer-area">
      {error ? (
        <div className="error-block">
          <p className="error-text">{error}</p>
          <button className="retry-btn" onClick={onRetry}>Try again</button>
        </div>
      ) : (
        <p className="answer-text" aria-live="polite">{answer}</p>
      )}
    </div>
  )
}
