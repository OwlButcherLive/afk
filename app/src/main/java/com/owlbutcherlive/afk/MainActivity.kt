package com.owlbutcherlive.afk

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.*
import com.owlbutcherlive.afk.core.ui.theme.AfkTheme
import com.owlbutcherlive.afk.feature.connection.contract.ConnectionEffect
import com.owlbutcherlive.afk.feature.connection.ui.ConnectionScreen
import com.owlbutcherlive.afk.feature.dashboard.ui.DashboardScreen
import com.owlbutcherlive.afk.feature.chat.ui.ChatScreen
import com.owlbutcherlive.afk.feature.sessions.ui.SessionsScreen

/**
 * Navigation state for the main screens.
 */
private sealed interface Screen {
    data object Connection : Screen
    data object Dashboard : Screen
    data object Sessions : Screen
    data class Chat(
        val sessionId: String,
        val sessionTitle: String,
        val agentId: String = ""
    ) : Screen
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AfkTheme {
                var screen by remember { mutableStateOf<Screen>(Screen.Connection) }

                when (screen) {
                    is Screen.Connection -> {
                        ConnectionScreen(
                            onConnected = {
                                screen = Screen.Dashboard
                            }
                        )
                    }
                    is Screen.Dashboard -> {
                        DashboardScreen(
                            onDisconnected = {
                                screen = Screen.Connection
                            },
                            onSessionsList = {
                                screen = Screen.Sessions
                            }
                        )
                    }
                    is Screen.Sessions -> {
                        SessionsScreen(
                            onSessionSelected = { sessionId, title, agentId ->
                                screen = Screen.Chat(sessionId, title, agentId)
                            },
                            onBack = {
                                screen = Screen.Dashboard
                            }
                        )
                    }
                    is Screen.Chat -> {
                        @Suppress("UNCHECKED_CAST")
                        val chat = screen as Screen.Chat
                        ChatScreen(
                            sessionId = chat.sessionId,
                            sessionTitle = chat.sessionTitle,
                            sessionAgentId = chat.agentId,
                            onBack = {
                                screen = Screen.Sessions
                            }
                        )
                    }
                }
            }
        }
    }
}
