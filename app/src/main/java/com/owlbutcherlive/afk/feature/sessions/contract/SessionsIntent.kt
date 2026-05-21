package com.owlbutcherlive.afk.feature.sessions.contract

import com.owlbutcherlive.afk.domain.ChatSession

sealed interface SessionsIntent {
    data object LoadSessions : SessionsIntent
    data object CreateNewSession : SessionsIntent
    data class SelectAgent(val agentId: String) : SessionsIntent
    data object DismissAgentPicker : SessionsIntent
    data object RetryLoad : SessionsIntent
}
