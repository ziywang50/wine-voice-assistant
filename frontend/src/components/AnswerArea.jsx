import { useState, useCallback, useRef } from 'react'

export default function AnswerArea({ answer, audioBase64, error, status, onRetry }) {
  const [replaying, setReplaying] = useState(false)
  const replayAudioRef = useRef(null)

  const handleClick = useCallback(() => {
    if (!audioBase64) return

    if (replaying) {
      replayAudioRef.current?.pause()
      replayAudioRef.current = null
      setReplaying(false)
      return
    }

    const binary = atob(audioBase64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    const blob = new Blob([bytes], { type: 'audio/mpeg' })
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    replayAudioRef.current = audio
    setReplaying(true)
    audio.onended = () => { URL.revokeObjectURL(url); setReplaying(false) }
    audio.onerror = () => { URL.revokeObjectURL(url); setReplaying(false) }
    audio.play().catch(() => setReplaying(false))
  }, [audioBase64, replaying])

  if (!answer && !error) return null

  return (
    <div className="answer-area">
      {error ? (
        <div className="error-block">
          <p className="error-text">{error}</p>
          <button className="retry-btn" onClick={onRetry}>Try again</button>
        </div>
      ) : (
        <>
          {audioBase64 && (
            <button
              className={`replay-btn${replaying ? ' replay-btn--playing' : ''}`}
              onClick={handleClick}
              aria-label={replaying ? 'Stop audio' : 'Replay answer'}
            >
              {replaying ? (
                <svg viewBox="0 0 24 24" fill="currentColor" stroke="none">
                  <rect x="5" y="5" width="14" height="14" rx="2"/>
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                  <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
                  <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                </svg>
              )}
            </button>
          )}
          <p className="answer-text" aria-live="polite">{answer}</p>
        </>
      )}
    </div>
  )
}
