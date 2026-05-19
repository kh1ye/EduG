'use client'

/**
 * /study - 瀛︿範椤甸潰
 * 
 * 娴佺▼锛? * 1. 娌℃湁 doc 鍙傛暟 -> 鏄剧ず鏂囨。閫夋嫨鐣岄潰
 * 2. 鏈?doc 浣嗘病鏈?chapter -> 鏄剧ず绔犺妭閫夋嫨鐣岄潰
 * 3. 鏈?doc 鍜?chapter -> 鏄剧ず瀛︿範瀵硅瘽鐣岄潰
 */

import { useState, useEffect, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { BookOpen, ChevronRight, Lock, CheckCircle2, Loader2, ArrowLeft, Settings, MessageSquare } from 'lucide-react'
import { getApiUrl, fetchWithTimeout, getAuthHeadersSimple, fetchWithCache } from '@/lib/config'
import { generateCacheKey } from '@/lib/cache'
import { StudyChat } from '@/components/chat/StudyChat'
import { SubsectionSelector } from '@/components/study/SubsectionSelector'
import { ProgressCard } from '@/components/progress/ProgressCard'
import { useAuth } from '@/contexts/AuthContext'
import Link from 'next/link'
import { DocumentListSkeleton, ChapterListSkeleton } from '@/components/ui/Skeleton'

interface Document {
  id: number
  title: string
  filename: string
  total_chapters: number
  processing_status: string
}

interface DocumentsListResponse {
  documents: Document[]
}

interface ChaptersListResponse {
  document_id: number
  document_title: string
  total_chapters: number
  chapters: any[]
}

interface Chapter {
  chapter_number: number
  chapter_title: string
  status: string
  completion_percentage: number
  is_locked: boolean
  lock_reason: string | null
  status_icon: string
  status_text: string
  subsections?: Subsection[]
  subsection_count?: number
}

interface Subsection {
  subsection_number: string
  subsection_title: string
  page_number?: number
  completion_percentage: number
  time_spent_minutes: number
}

function StudyPageContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { updateUser, user: authUser } = useAuth()  // 浣跨敤 AuthContext 鐨勬暟鎹拰鏂规硶

  const docId = searchParams.get('doc')
  const chapterId = searchParams.get('chapter')
  const subsectionId = searchParams.get('subsection')  // 鏂板灏忚妭鍙傛暟

  const [documents, setDocuments] = useState<Document[]>([])
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null)
  const [selectedChapter, setSelectedChapter] = useState<Chapter | null>(null)
  const [loading, setLoading] = useState(true)
  const [teachingStyle, setTeachingStyle] = useState(3)  // 榛樿 L3
  const [expandedChapter, setExpandedChapter] = useState<number | null>(null)  // 鎺у埗绔犺妭灞曞紑
  const [currentSubsection, setCurrentSubsection] = useState<Subsection | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [itemsPerPage] = useState(6)

  useEffect(() => {
    if (authUser?.teachingStyle !== null && authUser?.teachingStyle !== undefined) {
      setTeachingStyle(authUser.teachingStyle)
      console.log(`[Study] 浠?AuthContext 璇诲彇椋庢牸: L${authUser.teachingStyle}`)
    } else {
      // 鍥為€€锛氫粠 localStorage 璇诲彇
      const teachingStyleStr = localStorage.getItem('teaching_style')
      const userStr = localStorage.getItem('user')

      let style = 3  // 榛樿 L3

      if (teachingStyleStr) {
        style = parseInt(teachingStyleStr, 10)
        console.log(`[Study] 浠?'teaching_style' 閿鍙栭鏍? L${style}`)
      } else if (userStr) {
        try {
          const user = JSON.parse(userStr)
          if (user?.teachingStyle) {
            style = user.teachingStyle
            console.log(`[Study] 浠?'user' 瀵硅薄璇诲彇椋庢牸: L${style}`)
          }
        } catch {
          // 蹇界暐瑙ｆ瀽閿欒
        }
      }

      setTeachingStyle(style)
    }
  }, [authUser?.id, authUser?.teachingStyle])  // 鐩戝惉 authUser 鐨勫彉鍖?
  // 鍔犺浇鏂囨。鍒楄〃
  useEffect(() => {
    if (!docId) {
      loadDocuments()
    }
  }, [docId])

  // 鍔犺浇绔犺妭鍒楄〃
  useEffect(() => {
    if (docId && !chapterId) {
      loadChapters(parseInt(docId))
    }
  }, [docId, chapterId])

  useEffect(() => {
    if (docId && chapterId) {
      const chapterNum = parseInt(chapterId)
      if (!isNaN(chapterNum)) {
        loadSelectedChapter(parseInt(docId), chapterNum)
      }
    }
  }, [docId, chapterId])

  const loadDocuments = async () => {
    console.log('馃攧 [Study] 鍔犺浇鏂囨。鍒楄〃...')
    try {
      const cacheKey = generateCacheKey('documents', {})
      const data = await fetchWithCache<DocumentsListResponse>(
        getApiUrl('/api/documents/list'),
        {
          method: 'GET',
          headers: getAuthHeadersSimple()
        },
        cacheKey,
        { ttl: 5 * 60 * 1000, persistent: true }  // 5鍒嗛挓缂撳瓨锛屾寔涔呭寲
      )

      console.log('馃摜 [Study] 鍝嶅簲鐘舵€? 200 (缂撳瓨)')
      setDocuments(data.documents || [])
    } catch (err) {
      console.error('鉂?[Study] 鍔犺浇鏂囨。澶辫触:', err)
      // 涓嶆竻绌烘枃妗ｅ垪琛紝淇濇寔宸叉湁鏁版嵁
    } finally {
      setLoading(false)
    }
  }

  const loadChapters = async (documentId: number) => {
    try {
      const cacheKey = generateCacheKey('chapters', { documentId, v: 2 })
      const data = await fetchWithCache<ChaptersListResponse>(
        getApiUrl(`/api/documents/${documentId}/chapters`),
        {
          method: 'GET',
          headers: getAuthHeadersSimple()
        },
        cacheKey,
        { ttl: 30 * 1000, persistent: false }
      )

      setSelectedDoc({
        id: data.document_id,
        title: data.document_title,
        filename: data.document_title,
        total_chapters: data.total_chapters,
        processing_status: 'completed'
      })
      setChapters(data.chapters || [])
      setCurrentPage(1)
    } catch (err) {
      console.error('鉂?[Study] 鍔犺浇绔犺妭澶辫触:', err)
    } finally {
      setLoading(false)
    }
  }

  const loadSelectedChapter = async (documentId: number, chapterNumber: number) => {
    try {
      const response = await fetchWithTimeout(
        getApiUrl(`/api/documents/${documentId}/chapters`),
        {
          method: 'GET',
          headers: getAuthHeadersSimple()
        },
        60000
      )

      if (response.ok) {
        const data = await response.json()
        setSelectedDoc({
          id: data.document_id,
          title: data.document_title,
          filename: data.document_title,
          total_chapters: data.total_chapters,
          processing_status: 'completed'
        })

        const chapter = data.chapters.find((c: Chapter) => c.chapter_number === chapterNumber)
        if (chapter) {
          setSelectedChapter(chapter)
        }
      }
    } catch (err) {
      console.error('鉂?[Study] 鍔犺浇绔犺妭澶辫触:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleStyleChange = async (style: number) => {
    console.log(`[Study] 鍒囨崲鏁欏椋庢牸: L${teachingStyle} 鈫?L${style}`)

    try {
      // 鑾峰彇鐢ㄦ埛ID
      const userStr = localStorage.getItem('user')
      if (!userStr) {
        console.warn('[Study] 鏈壘鍒扮敤鎴蜂俊鎭紝鏃犳硶淇濆瓨椋庢牸')
        setTeachingStyle(style)
        return
      }

      const user = JSON.parse(userStr)
      const userId = user.id

      // 璋冪敤 API 鏇存柊鏁欏椋庢牸
      const response = await fetch(getApiUrl(`/api/users/${userId}/teaching-style`), {
        method: 'PUT',
        headers: {
          ...getAuthHeadersSimple(),
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ teaching_style: style })
      })

      if (response.ok) {
        console.log('[Study] teaching style saved to database')

        updateUser({ teachingStyle: style })

        // 涔熸洿鏂?user 瀵硅薄锛堜繚鎸佸悜鍚庡吋瀹癸級
        user.teachingStyle = style
        localStorage.setItem('user', JSON.stringify(user))

        setTeachingStyle(style)

        console.log('[Study] 鉁?鍏ㄥ眬鐘舵€佸凡鏇存柊:', {
          'teaching_style': localStorage.getItem('teaching_style'),
          'user.teachingStyle': JSON.parse(localStorage.getItem('user') || '{}').teachingStyle
        })
      } else {
        const errorData = await response.json()
        console.error('[Study] 鉂?淇濆瓨鏁欏椋庢牸澶辫触:', response.status, errorData)
        setTeachingStyle(style)
      }
    } catch (error) {
      console.error('[Study] 鉂?淇濆瓨鏁欏椋庢牸鍑洪敊:', error)
      setTeachingStyle(style)
    }
  }

  const handleSubsectionChange = (subsection: Subsection | null) => {
    setCurrentSubsection(subsection)

    // 鏇存柊URL锛屾坊鍔犳垨绉婚櫎subsection鍙傛暟
    if (subsection) {
      router.push(`/study?doc=${docId}&chapter=${chapterId}&subsection=${subsection.subsection_number}`)
    } else {
      router.push(`/study?doc=${docId}&chapter=${chapterId}`)
    }
  }

  // 褰揢RL涓殑subsection鍙傛暟鍙樺寲鏃讹紝鏇存柊currentSubsection
  useEffect(() => {
    if (selectedChapter && selectedChapter.subsections) {
      const subsection = selectedChapter.subsections.find(s => s.subsection_number === subsectionId)
      setCurrentSubsection(subsection || null)
    }
  }, [subsectionId, selectedChapter])

  // 1. 鏂囨。閫夋嫨鐣岄潰
  if (!docId) {
    return (
      <div className="min-h-screen bg-white">
        <div className="max-w-6xl mx-auto px-6 py-12">
          {/* 鏍囬 */}
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-black mb-2">选择学习教材</h1>
            <p className="text-gray-600">从您上传的教材中选择一本开始学习</p>
          </div>

          {/* 鏂囨。鍒楄〃 */}
          {loading ? (
            <DocumentListSkeleton count={6} />
          ) : documents.length === 0 ? (
            <div className="text-center py-20">
              <BookOpen className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <p className="text-gray-600 mb-6">还没有上传任何教材</p>
              <Link
                href="/documents"
                className="inline-block px-6 py-3 bg-black text-white rounded-xl hover:bg-gray-800 transition-colors"
              >
                上传教材
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {documents.map((doc) => (
                <motion.button
                  key={doc.id}
                  onClick={() => router.push(`/study?doc=${doc.id}`)}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  whileHover={{ y: -4 }}
                  className="p-6 bg-white border-2 border-gray-200 rounded-2xl hover:border-black transition-all text-left group"
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="p-3 bg-black text-white rounded-xl group-hover:scale-110 transition-transform">
                      <BookOpen className="w-6 h-6" />
                    </div>
                    <div className="text-sm text-gray-500">
                      {doc.total_chapters} 章节
                    </div>
                  </div>

                  <h3 className="font-semibold text-lg text-black mb-2 line-clamp-2">
                    {doc.title}
                  </h3>

                  <div className="flex items-center text-sm text-gray-600 group-hover:text-black transition-colors">
                    <span>开始学习</span>
                    <ChevronRight className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
                  </div>
                </motion.button>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  // 2. 绔犺妭閫夋嫨鐣岄潰
  if (docId && !chapterId) {
    return (
      <div className="min-h-screen bg-white">
        <div className="max-w-4xl mx-auto px-6 py-12">
          {/* 杩斿洖鎸夐挳 */}
          <button
            onClick={() => router.push('/study')}
            className="flex items-center gap-2 text-gray-600 hover:text-black mb-8 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
            返回教材列表
          </button>

          {/* 鏂囨。鏍囬 */}
          {selectedDoc && (
            <div className="mb-8">
              <h1 className="text-3xl font-bold text-black mb-2">{selectedDoc.title}</h1>
              <p className="text-gray-600">共 {selectedDoc.total_chapters} 个章节</p>
            </div>
          )}

          {/* 绔犺妭鍒楄〃 */}
          {loading ? (
            <ChapterListSkeleton count={6} />
          ) : (
            <>
              {/* 鍒嗛〉鐨勭珷鑺傚垪琛?*/}
              <div className="space-y-4">
                {chapters
                  .slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
                  .map((chapter, index) => (
                <motion.div
                  key={`chapter-${chapter.chapter_number}-${index}`}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className={`p-6 rounded-2xl border-2 ${
                    chapter.is_locked
                      ? 'bg-gray-50 border-gray-200 opacity-60'
                      : 'bg-white border-gray-200 hover:border-black hover:shadow-lg'
                  }`}
                >
                  <div className="flex items-center gap-4 mb-4">
                    {/* 绔犺妭鍥炬爣 */}
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 ${
                      chapter.is_locked
                        ? 'bg-gray-200 text-gray-400'
                        : chapter.status === 'completed'
                        ? 'bg-green-100 text-green-600'
                        : 'bg-black text-white'
                    }`}>
                      {chapter.is_locked ? (
                        <Lock className="w-6 h-6" />
                      ) : chapter.status === 'completed' ? (
                        <CheckCircle2 className="w-6 h-6" />
                      ) : (
                        <span className="text-lg font-bold">{chapter.chapter_number}</span>
                      )}
                    </div>

                    {/* 绔犺妭淇℃伅 */}
                    <div className="flex-1">
                      <h3 className="font-semibold text-lg text-black mb-1">
                        {chapter.chapter_title}
                      </h3>
                      <div className="flex items-center gap-4 text-sm">
                        <span className={`${
                          chapter.is_locked ? 'text-gray-400' : 'text-gray-600'
                        }`}>
                          {chapter.status_text}
                        </span>
                        {!chapter.is_locked && chapter.completion_percentage > 0 && (
                          <span className="text-gray-600">
                            完成度 {Math.round(chapter.completion_percentage)}%
                          </span>
                        )}
                      </div>
                      {chapter.is_locked && chapter.lock_reason && (
                        <p className="text-xs text-gray-500 mt-2">{chapter.lock_reason}</p>
                      )}
                    </div>
                  </div>

                  {/* 杩涘害鏉?*/}
                  {!chapter.is_locked && chapter.completion_percentage > 0 && (
                    <div className="mb-4 w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                      <motion.div
                        className="h-full bg-black rounded-full"
                        initial={{ width: 0 }}
                        animate={{ width: `${chapter.completion_percentage}%` }}
                        transition={{ duration: 0.8, ease: 'easeOut' }}
                      />
                    </div>
                  )}

                  {/* 灏忚妭鍒楄〃 */}
                  {chapter.subsections && chapter.subsections.length > 0 && (
                    <div className="mb-4">
                      <button
                        onClick={() => setExpandedChapter(expandedChapter === chapter.chapter_number ? null : chapter.chapter_number)}
                        className="flex items-center gap-2 text-sm text-gray-600 hover:text-black mb-2 transition-colors"
                      >
                        <ChevronRight
                          className={`w-4 h-4 transition-transform ${
                            expandedChapter === chapter.chapter_number ? 'rotate-90' : ''
                          }`}
                        />
                        <span>{chapter.subsection_count} 个小节</span>
                      </button>

                      <AnimatePresence>
                        {expandedChapter === chapter.chapter_number && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2 }}
                            className="overflow-hidden"
                          >
                            <div className="pl-6 pr-2 pb-2 space-y-1">
                              {chapter.subsections.map((subsection) => (
                                <div
                                  key={subsection.subsection_number}
                                  className="flex items-center gap-2 group"
                                >
                                  {/* 灏忚妭淇℃伅 */}
                                  <div className="flex-1 px-3 py-2 rounded-lg bg-gray-50 flex items-center gap-2">
                                    <span className="text-xs font-medium text-gray-500">
                                      {subsection.subsection_number}
                                    </span>
                                    <span className="text-sm text-gray-700 flex-1">
                                      {subsection.subsection_title}
                                    </span>
                                  </div>

                                  {/* 鎿嶄綔鎸夐挳 */}
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      router.push(`/study?doc=${docId}&chapter=${chapter.chapter_number}&subsection=${subsection.subsection_number}`)
                                    }}
                                    className="p-2 rounded-lg bg-gray-50 hover:bg-black hover:text-white transition-colors"
                                    title="学习对话"
                                  >
                                    <MessageSquare className="w-4 h-4" />
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      router.push(`/quiz?doc=${docId}&chapter=${chapter.chapter_number}&subsection=${subsection.subsection_number}`)
                                    }}
                                    className="p-2 rounded-lg bg-gray-50 hover:bg-black hover:text-white transition-colors"
                                    title="小节测试"
                                  >
                                    <BookOpen className="w-4 h-4" />
                                  </button>
                                </div>
                              ))}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )}

                  {/* 鎿嶄綔鎸夐挳 */}
                  {!chapter.is_locked && (
                    <div className="flex gap-3">
                      <button
                        onClick={() => router.push(`/study?doc=${docId}&chapter=${chapter.chapter_number}`)}
                        className="flex-1 px-4 py-2 bg-black text-white rounded-xl hover:bg-gray-800 transition-colors flex items-center justify-center gap-2"
                      >
                        <MessageSquare className="w-4 h-4" />
                        <span>学习对话</span>
                      </button>
                      <button
                        onClick={() => router.push(`/quiz?doc=${docId}&chapter=${chapter.chapter_number}`)}
                        className="flex-1 px-4 py-2 border-2 border-black text-black rounded-xl hover:bg-black hover:text-white transition-colors flex items-center justify-center gap-2"
                      >
                        <BookOpen className="w-4 h-4" />
                        <span>章节测试</span>
                      </button>
                    </div>
                  )}
                </motion.div>
              ))}
            </div>

            {/* 鍒嗛〉鎺т欢 */}
            {chapters.length > itemsPerPage && (
              <div className="flex items-center justify-center gap-4 mt-8 pt-4 border-t border-gray-200">
                <button
                  onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className={`px-4 py-2 rounded-lg transition-colors ${
                    currentPage === 1
                      ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                      : 'bg-white border-2 border-gray-200 hover:border-black hover:shadow-md'
                  }`}
                >
                  上一页
                </button>

                <div className="flex items-center gap-2">
                  {Array.from({ length: Math.ceil(chapters.length / itemsPerPage) }, (_, i) => i + 1).map(pageNum => (
                    <button
                      key={pageNum}
                      onClick={() => setCurrentPage(pageNum)}
                      className={`w-10 h-10 rounded-lg font-medium transition-colors ${
                        currentPage === pageNum
                          ? 'bg-black text-white'
                          : 'bg-white border-2 border-gray-200 hover:border-black hover:shadow-md'
                      }`}
                    >
                      {pageNum}
                    </button>
                  ))}
                </div>

                <button
                  onClick={() => setCurrentPage(p => Math.min(Math.ceil(chapters.length / itemsPerPage), p + 1))}
                  disabled={currentPage === Math.ceil(chapters.length / itemsPerPage)}
                  className={`px-4 py-2 rounded-lg transition-colors ${
                    currentPage === Math.ceil(chapters.length / itemsPerPage)
                      ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                      : 'bg-white border-2 border-gray-200 hover:border-black hover:shadow-md'
                  }`}
                >
                  下一页
                </button>

                <span className="text-sm text-gray-500">
                  第 {currentPage} / {Math.ceil(chapters.length / itemsPerPage)} 页
                </span>
              </div>
            )}
          </>
          )}
        </div>
      </div>
    )
  }

  // 3. 瀛︿範瀵硅瘽鐣岄潰
  if (docId && chapterId && selectedChapter) {
    return (
      <div className="fixed inset-0 bg-white z-40 flex">
        {/* 宸︿晶锛氬涔犺繘搴﹀崱鐗?*/}
        <div className="w-80 border-r border-gray-200 overflow-y-auto hidden lg:block">
          <div className="p-6">
            {authUser && authUser.id && (
              <ProgressCard
                userId={authUser.id}
                documentId={parseInt(docId)}
                chapterNumber={parseInt(chapterId)}
              />
            )}
          </div>
        </div>

        {/* 鍙充晶锛氬璇濆尯鍩?*/}
        <div className="flex-1 flex flex-col">
          {/* 椤堕儴瀵艰埅鏍?*/}
          <div className="border-b border-gray-200 bg-white flex-shrink-0">
          <div className="max-w-7xl mx-auto px-6 py-4">
            <div className="flex items-center justify-between">
              {/* 宸︿晶锛氳繑鍥炲拰鏍囬 */}
              <div className="flex items-center gap-4">
                <button
                  onClick={() => router.push(`/study?doc=${docId}`)}
                  className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <ArrowLeft className="w-5 h-5 text-gray-600" />
                </button>
                <div>
                  <h1 className="font-semibold text-lg text-black">
                    {selectedChapter.chapter_title}
                  </h1>
                  <p className="text-sm text-gray-500">{selectedDoc?.title}</p>
                </div>

                {/* 灏忚妭閫夋嫨鍣?*/}
                {selectedChapter.subsection_count && selectedChapter.subsection_count > 0 && (
                  <div className="ml-4">
                    <SubsectionSelector
                      documentId={parseInt(docId)}
                      chapterId={parseInt(chapterId)}
                      chapterTitle={selectedChapter.chapter_title}
                      currentSubsection={subsectionId ?? undefined}
                      onSubsectionChange={handleSubsectionChange}
                    />
                  </div>
                )}
              </div>

              {/* 鍙充晶锛氬甯堥鏍煎拰杩涘害 */}
              <div className="flex items-center gap-4">
                {/* 绔犺妭娴嬭瘯鎸夐挳 */}
                <button
                  onClick={() => router.push(`/quiz?doc=${docId}&chapter=${chapterId}`)}
                  className="px-4 py-2 border-2 border-black text-black rounded-xl hover:bg-black hover:text-white transition-colors flex items-center gap-2"
                >
                  <BookOpen className="w-4 h-4" />
                  <span className="text-sm font-medium">章节测试</span>
                </button>

                {/* 瀵煎笀椋庢牸鍒囨崲鍣?*/}
                <div className="relative group">
                  <button className="flex items-center gap-3 px-4 py-2 bg-black text-white rounded-xl hover:bg-gray-800 transition-colors">
                    <Settings className="w-4 h-4" />
                    <span className="text-sm font-medium">
                      L{teachingStyle} {
                        teachingStyle === 1 ? '温柔' :
                        teachingStyle === 2 ? '耐心' :
                        teachingStyle === 3 ? '标准' :
                        teachingStyle === 4 ? '严格' : '严厉'
                      }
                    </span>
                  </button>

                  {/* 涓嬫媺鑿滃崟 */}
                  <div className="absolute right-0 top-full mt-2 w-56 bg-white rounded-xl shadow-lg border border-gray-200 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
                    <div className="p-2">
                      <p className="text-xs text-gray-500 px-3 py-2">选择导师风格</p>
                      {[
                        { level: 1, label: 'L1 温柔', desc: '耐心细致，循序渐进' },
                        { level: 2, label: 'L2 耐心', desc: '详细讲解，注重基础' },
                        { level: 3, label: 'L3 标准', desc: '平衡严谨，注重应用' },
                        { level: 4, label: 'L4 严格', desc: '注重细节，深入理解' },
                        { level: 5, label: 'L5 严厉', desc: '挑战思维，独立解决' }
                      ].map((style) => (
                        <button
                          key={style.level}
                          onClick={() => handleStyleChange(style.level)}
                          className={`w-full text-left px-3 py-2 rounded-lg hover:bg-gray-50 transition-colors ${
                            teachingStyle === style.level ? 'bg-gray-100' : ''
                          }`}
                        >
                          <div className="font-medium text-sm text-black">{style.label}</div>
                          <div className="text-xs text-gray-500">{style.desc}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* 绔犺妭杩涘害 */}
                {selectedChapter.completion_percentage > 0 && (
                  <div className="flex items-center gap-2">
                    <div className="w-32 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <motion.div
                        className="h-full bg-black rounded-full"
                        initial={{ width: 0 }}
                        animate={{ width: `${selectedChapter.completion_percentage}%` }}
                        transition={{ duration: 0.8 }}
                      />
                    </div>
                    <span className="text-sm text-gray-600">
                      {Math.round(selectedChapter.completion_percentage)}%
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* 涓诲涔犲尯鍩?- 鍏ㄥ睆瀵硅瘽 */}
        <div className="flex-1 overflow-hidden min-h-0">
          <StudyChat
            key={`${docId}-${chapterId}-${currentSubsection?.subsection_number || 'global'}`}
            chapterId={chapterId}
            chapterTitle={selectedChapter.chapter_title}
            subsectionId={currentSubsection?.subsection_number}
            subsectionTitle={currentSubsection?.subsection_title}
            documentId={parseInt(docId)}
            teachingStyle={teachingStyle}
          />
        </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center h-screen bg-white">
      <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
    </div>
  )
}

export default function StudyPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-screen bg-white">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    }>
      <StudyPageContent />
    </Suspense>
  )
}

