package com.owlbutcherlive.afk.feature.chat.contract

import com.owlbutcherlive.afk.domain.ChatAgent
import com.owlbutcherlive.afk.domain.ChatMessage

/**
 * Represents the complete UI state for the chat screen.
 */
data class ChatUiState(
    val messages: List<ChatMessage> = emptyList(),
    val inputText: String = "",
    val isLoadingHistory: Boolean = true,
    val historyError: String? = null,
    val connectionState: ChatConnectionState = ChatConnectionState.Connecting,
    val currentAgent: ChatAgent? = null,
    val isAgentTyping: Boolean = false,
    val sendError: String? = null
)

enum class ChatConnectionState {
    Connecting,
    Connected,
    Disconnected,
    Failed
}
