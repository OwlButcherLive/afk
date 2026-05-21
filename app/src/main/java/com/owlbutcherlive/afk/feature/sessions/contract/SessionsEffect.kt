package com.owlbutcherlive.afk.feature.sessions.contract

sealed interface SessionsEffect {
    data class NavigateToSession(val sessionId: String, val sessionTitle: String) : SessionsEffect
    data object NavigateBack : SessionsEffect
}
