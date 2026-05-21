package com.owlbutcherlive.afk.domain

import com.owlbutcherlive.afk.domain.MessageRole.Companion.fromApi

/**
 * Typed chat events received from the Agent Gateway WebSocket.
 */
sealed interface ChatEvent {
    data class Message(
        val id: String,
        val agentId: String,
        val role: MessageRole,
        val text: String,
        val timestamp: String
    ) : ChatEvent

    data class Typing(
        val agentId: String,
        val isTyping: Boolean
    ) : ChatEvent

    data class Error(
        val code: String,
        val message: String
    ) : ChatEvent

    data class AgentStatus(
        val agentId: String,
        val status: AgentOnlineStatus
    ) : ChatEvent
}
