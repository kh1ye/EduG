'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { Bot } from 'lucide-react'
import { MarkdownContent } from './MarkdownContent'

function fixIncompleteMarkdown(content: string): string {
  let fixed = content

  const codeBlockCount = (content.match(/```/g) || []).length
  if (codeBlockCount % 2 !== 0 && content.length > 50) {
    fixed += '\n```'
  }

  const inlineCodeCount = (content.match(/`/g) || []).length
  if (inlineCodeCount % 2 !== 0) {
    fixed += '`'
  }

  const mathBlockCount = (content.match(/\$\$/g) || []).length
  if (mathBlockCount % 2 !== 0) {
    fixed += '$$'
  }

  return fixed
}

interface StreamingMessageProps {
  content: string
  isComplete?: boolean
  isStreaming?: boolean
  streamProgress?: {
    received: number
    estimatedTotal: number
  }
}

export function StreamingMessage({
  content,
  isComplete = false,
  isStreaming = false,
  streamProgress
}: StreamingMessageProps) {
  const renderContent = isComplete ? content : fixIncompleteMarkdown(content)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="group relative px-4 py-6 hover:bg-gray-50/50 transition-colors"
    >
      <div className="mx-auto max-w-4xl">
        <div className="flex gap-4">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-gray-900 shadow-sm ring-2 ring-white">
            <Bot className="h-5 w-5 text-white" />
          </div>

          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900">AI 导师</span>
                {!isComplete && (
                  <span className="text-xs text-gray-400">正在输入...</span>
                )}
              </div>

              {isStreaming && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="flex items-center gap-2 text-xs text-gray-500"
                >
                  <div className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
                  <span>正在生成回复...</span>
                </motion.div>
              )}
            </div>

            {streamProgress && isStreaming && (
              <div className="text-xs text-gray-400">
                {streamProgress.received} / {streamProgress.estimatedTotal} 字符
              </div>
            )}

            <div className="max-w-4xl">
              <div className="overflow-hidden rounded-2xl rounded-tl-sm border border-gray-200 bg-white shadow-sm">
                <div className="p-6">
                  <MarkdownContent content={renderContent} isStreaming={!isComplete} />
                </div>
              </div>
            </div>

            <AnimatePresence>
              {!isComplete && (
                <motion.span
                  initial={{ opacity: 1 }}
                  animate={{ opacity: [1, 0, 1] }}
                  exit={{ opacity: 0 }}
                  transition={{
                    duration: 0.8,
                    repeat: Infinity,
                    ease: 'easeInOut'
                  }}
                  className="ml-1 inline-block h-4 w-0.5 bg-black"
                />
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
