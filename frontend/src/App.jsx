import { useVoice } from './hooks/useVoice'
import MicButton from './components/MicButton'
import StatusLabel from './components/StatusLabel'
import TranscriptArea from './components/TranscriptArea'
import AnswerArea from './components/AnswerArea'
import './App.css'

export default function App() {
  const { status, transcript, answer, error, toggleRecording, cancel, reset } = useVoice()

  return (
    <div className="app">
      <header className="app-header">
        <div className="logo" aria-hidden="true">🍷</div>
        <h1>Wine Sommelier</h1>
        <p className="subtitle">Ask me anything about our wine collection</p>
      </header>

      <main className="app-main">
        <TranscriptArea transcript={transcript} status={status} />

        <div className="mic-section">
          <MicButton status={status} onClick={toggleRecording} onCancel={cancel} />
          <StatusLabel status={status} />
        </div>

        <AnswerArea answer={answer} error={error} status={status} onRetry={reset} />
      </main>
    </div>
  )
}
