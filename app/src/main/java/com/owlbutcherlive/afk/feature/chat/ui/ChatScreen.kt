package com.owlbutcherlive.afk.feature.chat.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.owlbutcherlive.afk.domain.ChatMessage
import com.owlbutcherlive.afk.domain.MessageRole
import com.owlbutcherlive.afk.feature.chat.contract.ChatConnectionState
import com.owlbutcherlive.afk.feature.chat.contract.ChatIntent
import com.owlbutcherlive.afk.feature.chat.presentation.ChatViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    viewModel: ChatViewModel = viewModel(),
    onBack: () -> Unit = {}
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()

    // Collect effects (navigation)
    LaunchedEffect(Unit) {
        viewModel.effects.collect { effect ->
            when (effect) {
                com.owlbutcherlive.afk.feature.chat.contract.ChatEffect.NavigateBack -> onBack()
                else -> {}
            }
        }
    }

    // Auto-scroll to bottom when new messages arrive
    val messageCount = state.messages.size
    LaunchedEffect(messageCount) {
        if (messageCount > 0) {
            listState.animateScrollToItem(messageCount - 1)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = state.currentAgent?.name ?: "Chat",
                            style = MaterialTheme.typography.titleMedium
                        )
                        Text(
                            text = connectionStatusLabel(state.connectionState),
                            style = MaterialTheme.typography.bodySmall,
                            color = connectionStatusColor(state.connectionState)
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = { viewModel.processIntent(ChatIntent.NavigateBack) }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    if (state.connectionState == ChatConnectionState.Failed ||
                        state.connectionState == ChatConnectionState.Disconnected
                    ) {
                        IconButton(onClick = { viewModel.processIntent(ChatIntent.Reconnect) }) {
                            Icon(Icons.Default.Refresh, contentDescription = "Reconnect")
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface
                )
            )
        },
        bottomBar = {
            ChatInputBar(
                text = state.inputText,
                onTextChange = { viewModel.processIntent(ChatIntent.UpdateInput(it)) },
                onSend = { viewModel.processIntent(ChatIntent.SendMessage) },
                enabled = state.connectionState == ChatConnectionState.Connected
            )
        }
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            when {
                // Loading history
                state.isLoadingHistory -> {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            CircularProgressIndicator()
                            Spacer(Modifier.height(12.dp))
                            Text(
                                text = "Loading messages...",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }

                // History error
                state.historyError != null -> {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier.padding(32.dp)
                        ) {
                            Icon(
                                Icons.Default.CloudOff,
                                contentDescription = null,
                                modifier = Modifier.size(48.dp),
                                tint = MaterialTheme.colorScheme.error
                            )
                            Spacer(Modifier.height(12.dp))
                            Text(
                                text = state.historyError ?: "",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.error,
                                textAlign = TextAlign.Center
                            )
                            Spacer(Modifier.height(16.dp))
                            OutlinedButton(
                                onClick = { viewModel.processIntent(ChatIntent.RetryLoadHistory) }
                            ) {
                                Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Retry")
                            }
                        }
                    }
                }

                // Empty state
                state.messages.isEmpty() && !state.isLoadingHistory -> {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier.padding(32.dp)
                        ) {
                            Icon(
                                Icons.Default.Chat,
                                contentDescription = null,
                                modifier = Modifier.size(48.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                            )
                            Spacer(Modifier.height(12.dp))
                            Text(
                                text = "No messages yet",
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                text = connectionEmptyLabel(state.connectionState),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                            )
                        }
                    }
                }

                // Message list
                else -> {
                    LazyColumn(
                        state = listState,
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        items(state.messages, key = { it.id }) { message ->
                            MessageBubble(message)
                        }

                        // Typing indicator
                        if (state.isAgentTyping) {
                            item {
                                TypingIndicator()
                            }
                        }

                        // Bottom spacer for input bar clearance
                        item {
                            Spacer(modifier = Modifier.height(8.dp))
                        }
                    }
                }
            }

            // Connection status banner at bottom of content area
            AnimatedVisibility(
                visible = state.connectionState == ChatConnectionState.Connecting ||
                        state.connectionState == ChatConnectionState.Disconnected ||
                        state.connectionState == ChatConnectionState.Failed,
                enter = fadeIn(),
                exit = fadeOut(),
                modifier = Modifier.align(Alignment.BottomCenter)
            ) {
                ConnectionBanner(state.connectionState)
            }

            // Send error snackbar
            state.sendError?.let { error ->
                Snackbar(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    action = {
                        TextButton(onClick = { /* auto-dismissed on next success */ }) {
                            Text("Dismiss")
                        }
                    }
                ) {
                    Text(error)
                }
            }
        }
    }
}

// ─── Message bubble ───────────────────────────────────────────────────────

@Composable
private fun MessageBubble(message: ChatMessage) {
    val isUser = message.role == MessageRole.USER
    val alignment = if (isUser) Arrangement.End else Arrangement.Start
    val shape = if (isUser) {
        RoundedCornerShape(16.dp, 4.dp, 16.dp, 16.dp)
    } else {
        RoundedCornerShape(4.dp, 16.dp, 16.dp, 16.dp)
    }
    val containerColor = if (isUser) {
        MaterialTheme.colorScheme.primaryContainer
    } else {
        MaterialTheme.colorScheme.secondaryContainer
    }
    val contentColor = if (isUser) {
        MaterialTheme.colorScheme.onPrimaryContainer
    } else {
        MaterialTheme.colorScheme.onSecondaryContainer
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = alignment
    ) {
        Surface(
            shape = shape,
            color = containerColor,
            shadowElevation = 1.dp,
            modifier = Modifier.widthIn(max = 280.dp)
        ) {
            Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                Text(
                    text = message.text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = contentColor
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = message.timestamp.takeLast(8).take(5), // HH:MM from ISO
                    style = MaterialTheme.typography.labelSmall,
                    color = contentColor.copy(alpha = 0.6f),
                    modifier = Modifier.align(if (isUser) Alignment.End else Alignment.Start)
                )
            }
        }
    }
}

// ─── Typing indicator ─────────────────────────────────────────────────────

@Composable
private fun TypingIndicator() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.Start
    ) {
        Surface(
            shape = RoundedCornerShape(4.dp, 16.dp, 16.dp, 16.dp),
            color = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.6f)
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text(
                    text = "●",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.5f)
                )
                Text(
                    text = "●",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.5f)
                )
                Text(
                    text = "●",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.5f)
                )
            }
        }
    }
}

// ─── Input bar ─────────────────────────────────────────────────────────────

@Composable
private fun ChatInputBar(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    enabled: Boolean
) {
    Surface(
        shadowElevation = 4.dp,
        color = MaterialTheme.colorScheme.surface
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp)
                .navigationBarsPadding(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedTextField(
                value = text,
                onValueChange = onTextChange,
                placeholder = { Text("Type a message...") },
                modifier = Modifier.weight(1f),
                singleLine = true,
                enabled = enabled,
                shape = RoundedCornerShape(24.dp)
            )

            FilledIconButton(
                onClick = onSend,
                enabled = enabled && text.isNotBlank(),
                modifier = Modifier.size(48.dp)
            ) {
                Icon(
                    Icons.Default.Send,
                    contentDescription = "Send",
                    modifier = Modifier.size(20.dp)
                )
            }
        }
    }
}

// ─── Connection banner ─────────────────────────────────────────────────────

@Composable
private fun ConnectionBanner(state: ChatConnectionState) {
    val (backgroundColor, text, icon) = when (state) {
        ChatConnectionState.Connecting -> Triple(
            MaterialTheme.colorScheme.tertiaryContainer,
            "Connecting to chat...",
            Icons.Default.HourglassEmpty
        )
        ChatConnectionState.Disconnected -> Triple(
            MaterialTheme.colorScheme.secondaryContainer,
            "Disconnected",
            Icons.Default.CloudOff
        )
        ChatConnectionState.Failed -> Triple(
            MaterialTheme.colorScheme.errorContainer,
            "Connection failed",
            Icons.Default.Error
        )
        else -> return
    }

    Surface(
        color = backgroundColor,
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                icon,
                contentDescription = null,
                modifier = Modifier.size(16.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

// ─── Helpers ───────────────────────────────────────────────────────────────

private fun connectionStatusLabel(state: ChatConnectionState): String = when (state) {
    ChatConnectionState.Connected -> "Connected"
    ChatConnectionState.Connecting -> "Connecting..."
    ChatConnectionState.Disconnected -> "Disconnected"
    ChatConnectionState.Failed -> "Failed"
}

@Composable
private fun connectionStatusColor(state: ChatConnectionState) = when (state) {
    ChatConnectionState.Connected -> MaterialTheme.colorScheme.primary
    ChatConnectionState.Connecting -> MaterialTheme.colorScheme.tertiary
    ChatConnectionState.Disconnected -> MaterialTheme.colorScheme.onSurfaceVariant
    ChatConnectionState.Failed -> MaterialTheme.colorScheme.error
}

private fun connectionEmptyLabel(state: ChatConnectionState): String = when (state) {
    ChatConnectionState.Connected -> "Send a message to start the conversation."
    ChatConnectionState.Connecting -> "Establishing connection..."
    ChatConnectionState.Disconnected -> "Connection lost."
    ChatConnectionState.Failed -> "Could not connect to chat."
}
