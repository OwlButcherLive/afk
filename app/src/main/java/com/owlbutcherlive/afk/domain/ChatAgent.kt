package com.owlbutcherlive.afk.domain

/**
 * Represents a chat agent available on the remote gateway.
 */
data class ChatAgent(
    val id: String,
    val name: String,
    val status: AgentOnlineStatus
)

enum class AgentOnlineStatus {
    ONLINE,
    OFFLINE,
    BUSY;

    companion object {
        fun fromApi(value: String): AgentOnlineStatus = when (value.lowercase()) {
            "online" -> ONLINE
            "offline" -> OFFLINE
            "busy" -> BUSY
            else -> ONLINE
        }
    }
}
