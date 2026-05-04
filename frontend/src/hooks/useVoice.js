import { useState, useRef, useCallback } from 'react'

/**
 * Status values:
 *  'idle'          — waiting for user
 *  'recording'     — mic active, capturing audio
 *  'transcribing'  — audio sent to /api/transcribe
 *  'thinking'      — transcript sent to /api/ask (Claude working)
 *  'speaking'      — TTS audio playing
 *  'error'         — something went wrong
 */

export function useVoice() {
  const [status, setStatus] = useState('idle')
  const [transcript, setTranscript] = useState('')
  const [answer, setAnswer] = useState('')
  const [audioBase64, setAudioBase64] = useState(null)
  const [error, setError] = useState(null)

  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const audioRef = useRef(null)
  const abortControllerRef = useRef(null)

  const reset = useCallback(() => {
    setTranscript('')
    setAnswer('')
    setAudioBase64(null)
    setError(null)
    setStatus('idle')
  }, [])

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
  }, [])

  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    stopAudio()
    setStatus('idle')
  }, [stopAudio])

  const startRecording = useCallback(async () => {
    setError(null)
    setAnswer('')
    setTranscript('')
    stopAudio()

    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError('Microphone access denied. Please allow microphone access and try again.')
      setStatus('error')
      return
    }

    chunksRef.current = []
    const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg'
    const recorder = new MediaRecorder(stream, { mimeType })

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }

    recorder.onstop = async () => {
      // Stop all tracks so mic indicator disappears
      stream.getTracks().forEach((t) => t.stop())

      const blob = new Blob(chunksRef.current, { type: mimeType })
      await handleAudioBlob(blob, mimeType)
    }

    recorder.start()
    mediaRecorderRef.current = recorder
    setStatus('recording')
  }, [stopAudio]) // eslint-disable-line react-hooks/exhaustive-deps

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
  }, [])

  const toggleRecording = useCallback(() => {
    if (status === 'recording') {
      stopRecording()
    } else if (status === 'idle' || status === 'error') {
      startRecording()
    }
  }, [status, startRecording, stopRecording])

  async function handleAudioBlob(blob, mimeType) {
    setStatus('transcribing')

    let transcript
    try {
      const ext = mimeType.includes('ogg') ? '.ogg' : '.webm'
      const formData = new FormData()
      formData.append('audio', blob, `recording${ext}`)
      abortControllerRef.current = new AbortController()
      const res = await fetch('/api/transcribe', { method: 'POST', body: formData, signal: abortControllerRef.current.signal })
      if (!res.ok) throw new Error(`Transcription failed (${res.status})`)
      const data = await res.json()
      transcript = data.transcript?.trim()
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(`Transcription error: ${err.message}`)
      setStatus('error')
      return
    }

    if (!transcript) {
      setError("Couldn't hear anything. Please try again.")
      setStatus('error')
      return
    }

    setTranscript(transcript)
    setStatus('thinking')

    let answerText, audioBase64
    try {
      abortControllerRef.current = new AbortController()
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: transcript }),
        signal: abortControllerRef.current.signal,
      })
      if (!res.ok) throw new Error(`Ask failed (${res.status})`)
      const data = await res.json()
      answerText = data.answer
      audioBase64 = data.audio_base64
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(`Assistant error: ${err.message}`)
      setStatus('error')
      return
    }

    setAnswer(answerText)
    setAudioBase64(audioBase64 ?? null)

    if (audioBase64) {
      setStatus('speaking')
      try {
        const binary = atob(audioBase64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
        const audioBlob = new Blob([bytes], { type: 'audio/mpeg' })
        const url = URL.createObjectURL(audioBlob)
        const audio = new Audio(url)
        audioRef.current = audio
        audio.onended = () => {
          URL.revokeObjectURL(url)
          setStatus('idle')
        }
        audio.onerror = () => {
          URL.revokeObjectURL(url)
          setStatus('idle')
        }
        await audio.play()
      } catch {
        setStatus('idle')
      }
    } else {
      setStatus('idle')
    }
  }

  return {
    status,
    transcript,
    answer,
    audioBase64,
    error,
    toggleRecording,
    cancel,
    reset,
  }
}
