'use client'

import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Clock3, FileText, RefreshCw, XCircle } from 'lucide-react'
import { fetchWithAuth } from '@/lib/api-client'
import { getApiUrl } from '@/lib/config'
import { useAuth } from '@/contexts/AuthContext'

interface QuizAttemptRecord {
  id: number
  question_id: number
  question_text: string
  user_answer: string
  correct_answer: string
  is_correct: boolean
  time_spent_seconds: number
  created_at: string | null
  document_id: number
  document_title: string
  chapter_number: number
  chapter_title?: string
  competency_dimension?: string
  difficulty?: number
  explanation?: string
}

export default function RecordsPage() {
  const { isAuthenticated } = useAuth()
  const [attempts, setAttempts] = useState<QuizAttemptRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const stats = useMemo(() => {
    const total = attempts.length
    const correct = attempts.filter((attempt) => attempt.is_correct).length
    return {
      total,
      correct,
      score: total ? Math.round((correct / total) * 100) : 0
    }
  }, [attempts])

  const loadRecords = async () => {
    if (!isAuthenticated) {
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)
    try {
      const response = await fetchWithAuth(getApiUrl('/api/quiz/attempts?page_size=100'))
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const data = await response.json()
      setAttempts(data.attempts || [])
    } catch (err) {
      console.error('Failed to load quiz records:', err)
      setError('加载测验记录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRecords()
  }, [isAuthenticated])

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-white px-8 py-10">
        <h1 className="text-3xl font-semibold text-gray-950">测验记录</h1>
        <p className="mt-3 text-gray-500">请先登录后查看答题记录。</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-gray-200 px-8 py-8">
        <div className="max-w-6xl">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-semibold text-gray-950">测验记录</h1>
              <p className="mt-2 text-sm text-gray-500">查看章节测验中每一道题的提交记录。</p>
            </div>
            <button
              onClick={loadRecords}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:border-gray-400 hover:bg-gray-50"
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl px-8 py-8">
        <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <p className="text-sm text-gray-500">已作答</p>
            <p className="mt-2 text-3xl font-semibold text-gray-950">{stats.total}</p>
          </div>
          <div className="rounded-xl border border-green-200 bg-green-50 p-5">
            <p className="text-sm text-green-700">答对</p>
            <p className="mt-2 text-3xl font-semibold text-green-900">{stats.correct}</p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <p className="text-sm text-gray-500">正确率</p>
            <p className="mt-2 text-3xl font-semibold text-gray-950">{stats.score}%</p>
          </div>
        </section>

        {loading ? (
          <div className="rounded-xl border border-gray-200 p-8 text-center text-gray-500">
            正在加载测验记录...
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-red-700">
            {error}
          </div>
        ) : attempts.length === 0 ? (
          <div className="rounded-xl border border-gray-200 p-12 text-center">
            <FileText className="mx-auto mb-4 h-10 w-10 text-gray-300" />
            <h2 className="text-lg font-semibold text-gray-950">还没有测验记录</h2>
            <p className="mt-2 text-sm text-gray-500">完成章节测验并提交答案后，这里会显示记录。</p>
          </div>
        ) : (
          <div className="space-y-4">
            {attempts.map((attempt) => (
              <article
                key={attempt.id}
                className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
              >
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-gray-950">
                      {attempt.document_title}
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                      第 {attempt.chapter_number} 章
                      {attempt.chapter_title ? ` · ${attempt.chapter_title}` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                      <Clock3 className="h-3.5 w-3.5" />
                      {attempt.created_at
                        ? new Date(attempt.created_at).toLocaleString('zh-CN')
                        : '未知时间'}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${
                        attempt.is_correct
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }`}
                    >
                      {attempt.is_correct ? (
                        <CheckCircle2 className="h-3.5 w-3.5" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5" />
                      )}
                      {attempt.is_correct ? '答对' : '答错'}
                    </span>
                  </div>
                </div>

                <h2 className="text-base font-semibold leading-7 text-gray-950">
                  {attempt.question_text}
                </h2>

                <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div className="rounded-lg bg-gray-50 p-3">
                    <p className="text-xs text-gray-500">你的答案</p>
                    <p className="mt-1 font-medium text-gray-950">{attempt.user_answer || '未作答'}</p>
                  </div>
                  <div className="rounded-lg bg-gray-50 p-3">
                    <p className="text-xs text-gray-500">正确答案</p>
                    <p className="mt-1 font-medium text-gray-950">{attempt.correct_answer}</p>
                  </div>
                </div>

                {attempt.explanation && (
                  <p className="mt-4 rounded-lg border border-gray-200 bg-white p-3 text-sm leading-6 text-gray-700">
                    {attempt.explanation}
                  </p>
                )}
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
