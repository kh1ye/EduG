'use client'

import React from 'react'
import { motion } from 'framer-motion'
import { Bot, Check, Copy, User } from 'lucide-react'
import { MarkdownContent } from './MarkdownContent'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

interface ChatMessageProps {
  message: Message
}

function arePropsEqual(prevProps: ChatMessageProps, nextProps: ChatMessageProps) {
  return (
    prevProps.message.id === nextProps.message.id &&
    prevProps.message.content === nextProps.message.content &&
    prevProps.message.role === nextProps.message.role &&
    prevProps.message.timestamp.getTime() === nextProps.message.timestamp.getTime()
  )
}

export const ChatMessage = React.memo(function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = React.useState(false)

  const handleCopy = React.useCallback(() => {
    navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [message.content])

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="group relative px-4 py-6 hover:bg-gray-50/50 transition-colors"
    >
      <div className="mx-auto max-w-4xl">
        <div className={`flex gap-4 ${isUser ? 'flex-row-reverse' : ''}`}>
          <div
            className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full shadow-sm ring-2 ring-white ${
              isUser ? 'bg-black' : 'bg-gray-900'
            }`}
          >
            {isUser ? (
              <User className="h-5 w-5 text-white" />
            ) : (
              <Bot className="h-5 w-5 text-white" />
            )}
          </div>

          <div className="min-w-0 flex-1 space-y-2">
            <div className={`flex items-center gap-2 ${isUser ? 'justify-end' : ''}`}>
              <span className="text-sm font-medium text-gray-900">
                {isUser ? '你' : 'AI 导师'}
              </span>
              <span className="text-xs text-gray-400">
                {message.timestamp.toLocaleTimeString('zh-CN', {
                  hour: '2-digit',
                  minute: '2-digit'
                })}
              </span>
            </div>

            <div className={`relative ${isUser ? 'ml-auto max-w-2xl' : 'max-w-4xl'}`}>
              {isUser ? (
                <div className="rounded-2xl rounded-tr-sm bg-black px-5 py-3 text-white shadow-sm">
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">
                    {message.content}
                  </p>
                </div>
              ) : (
                <div className="overflow-hidden rounded-2xl rounded-tl-sm border border-gray-200 bg-white shadow-sm">
                  <div className="p-6">
                    <MarkdownContent content={message.content} />
                  </div>

                  <div className="flex items-center justify-between border-t border-gray-200 bg-gray-50 px-6 py-3">
                    <button
                      onClick={handleCopy}
                      className="inline-flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-700 transition-all hover:bg-gray-200 hover:text-gray-900"
                    >
                      {copied ? (
                        <>
                          <Check className="h-3.5 w-3.5" />
                          <span>已复制</span>
                        </>
                      ) : (
                        <>
                          <Copy className="h-3.5 w-3.5" />
                          <span>复制</span>
                        </>
                      )}
                    </button>
                    <span className="text-xs text-gray-500">AI 生成内容</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  )
}, arePropsEqual)
