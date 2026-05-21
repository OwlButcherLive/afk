package com.owlbutcherlive.afk.feature.v2threads.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.owlbutcherlive.afk.core.network.V2Protocol
import com.owlbutcherlive.afk.feature.v2threads.contract.V2ThreadsIntent
import com.owlbutcherlive.afk.feature.v2threads.contract.V2ThreadsUiState
import com.owlbutcherlive.afk.feature.v2threads.presentation.V2ThreadsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun V2ThreadsScreen(
    viewModel: V2ThreadsViewModel = viewModel(),
    onBack: () -> Unit = {}
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(Unit) {
        viewModel.effects.collect { effect ->
            when (effect) {
                is com.owlbutcherlive.afk.feature.v2threads.contract.V2ThreadsEffect.ShowToast -> {
                    snackbarHostState.showSnackbar(effect.message)
                }
                is com.owlbutcherlive.afk.feature.v2threads.contract.V2ThreadsEffect.ShowError -> {
                    snackbarHostState.showSnackbar(effect.error)
                }
            }
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        if (state.selectedThreadId != null) state.selectedThreadTitle
                        else "V2 Debug"
                    )
                },
                navigationIcon = {
                    IconButton(onClick = {
                        if (state.selectedThreadId != null) {
                            viewModel.onIntent(V2ThreadsIntent.Disconnect)
                        } else {
                            onBack()
                        }
                    }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    if (state.selectedThreadId == null) {
                        IconButton(onClick = { viewModel.onIntent(V2ThreadsIntent.ToggleDebug) }) {
                            Icon(
                                if (state.showDebug) Icons.Default.VisibilityOff
                                else Icons.Default.Visibility,
                                contentDescription = "Toggle debug"
                            )
                        }
                        IconButton(onClick = { viewModel.onIntent(V2ThreadsIntent.ConnectWs) }) {
                            Icon(
                                if (state.wsConnected) Icons.Default.Wifi
                                else Icons.Default.WifiOff,
                                contentDescription = if (state.wsConnected) "WS connected" else "Connect WS"
                            )
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface
                )
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            if (state.selectedThreadId == null) {
                // Thread list view
                ThreadListView(
                    state = state,
                    onLoadThreads = { viewModel.onIntent(V2ThreadsIntent.LoadThreads) },
                    onOpenThread = { id, title ->
                        viewModel.onIntent(V2ThreadsIntent.OpenThread(id, title))
                    }
                )
            } else {
                // Thread detail / message view
                ThreadDetailView(
                    state = state,
                    onSendMessage = { text ->
                        viewModel.onIntent(V2ThreadsIntent.SendMessage(text))
                    },
                    onRefresh = { viewModel.onIntent(V2ThreadsIntent.Refresh) }
                )
            }

            // Debug panel (shown when on thread list and debug is enabled, or always on detail)
            if (state.selectedThreadId != null || state.showDebug) {
                DebugPanel(
                    state = state,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
    }
}

@Composable
private fun ThreadListView(
    state: V2ThreadsUiState,
    onLoadThreads: () -> Unit,
    onOpenThread: (String, String) -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        // Connection status bar
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Surface(
                color = if (state.wsConnected) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.errorContainer,
                shape = MaterialTheme.shapes.small,
                modifier = Modifier.height(8.dp).width(8.dp)
            ) {}
            Text(
                text = if (state.wsConnected) "WS Connected" else "WS Disconnected",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.weight(1f))
            if (state.isLoading) {
                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            }
        }

        // Load / Refresh button
        Button(
            onClick = onLoadThreads,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp)
        ) {
            Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(8.dp))
            Text("Load Threads")
        }

        if (state.threads.isEmpty() && !state.isLoading) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    "No threads loaded. Tap \"Load Threads\" to fetch.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                items(state.threads, key = { it.id }) { thread ->
                    ThreadCard(
                        title = thread.title,
                        status = thread.status,
                        runtimeKind = thread.runtime_kind,
                        turnCount = thread.turn_count,
                        lastMessage = thread.last_message_preview,
                        onClick = { onOpenThread(thread.id, thread.title) }
                    )
                }
            }
        }
    }
}

@Composable
private fun ThreadCard(
    title: String,
    status: String,
    runtimeKind: String,
    turnCount: Int,
    lastMessage: String,
    onClick: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = title.ifEmpty { "(untitled)" },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Surface(
                    color = if (status == "active") MaterialTheme.colorScheme.primaryContainer
                    else MaterialTheme.colorScheme.surface,
                    shape = MaterialTheme.shapes.extraSmall
                ) {
                    Text(
                        text = status,
                        style = MaterialTheme.typography.labelSmall,
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    text = "Runtime: $runtimeKind",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = "Turns: $turnCount",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (lastMessage.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = lastMessage,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

@Composable
private fun ThreadDetailView(
    state: V2ThreadsUiState,
    onSendMessage: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    var inputText by remember(state.selectedThreadId) { mutableStateOf("") }

    Column(modifier = Modifier.fillMaxSize()) {
        // Conversation header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "${state.messages.size} items",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.weight(1f))
            IconButton(onClick = onRefresh, modifier = Modifier.size(24.dp)) {
                Icon(Icons.Default.Refresh, contentDescription = "Refresh", modifier = Modifier.size(16.dp))
            }
        }

        // Messages list
        if (state.messages.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    "Waiting for snapshot...",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                items(state.messages, key = { it.id }) { item ->
                    MessageBubble(item)
                }
            }
        }

        // Input field
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedTextField(
                value = inputText,
                onValueChange = { inputText = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Type a message...") },
                singleLine = true,
                enabled = state.wsConnected
            )
            IconButton(
                onClick = {
                    if (inputText.isNotBlank()) {
                        onSendMessage(inputText)
                        inputText = ""
                    }
                },
                enabled = state.wsConnected && inputText.isNotBlank()
            ) {
                Icon(Icons.Default.Send, contentDescription = "Send")
            }
        }
    }
}

@Composable
private fun MessageBubble(item: V2Protocol.V2Item) {
    val isUser = item.role == "user"
    val bgColor = if (isUser) MaterialTheme.colorScheme.primaryContainer
    else MaterialTheme.colorScheme.secondaryContainer

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start
    ) {
        Surface(
            color = bgColor,
            shape = MaterialTheme.shapes.medium,
            modifier = Modifier.widthIn(max = 320.dp)
        ) {
            Column(modifier = Modifier.padding(8.dp)) {
                Text(
                    text = item.role,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = item.content.ifEmpty { "(empty)" },
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace
                )
                Text(
                    text = "kind=${item.kind} idx=${item.index}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
                )
            }
        }
    }
}

@Composable
private fun DebugPanel(state: V2ThreadsUiState, modifier: Modifier = Modifier) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.9f),
        modifier = modifier
    ) {
        Column(
            modifier = Modifier
                .padding(horizontal = 16.dp, vertical = 8.dp)
                .verticalScroll(rememberScrollState())
        ) {
            Text(
                text = "Debug Panel",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = "Status: ${state.statusMessage}",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = "Last Event: ${state.lastEventType}",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = "WS: ${if (state.wsConnected) "Connected" else "Disconnected"}",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = "Thread: ${state.selectedThreadId ?: "(none)"}",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = "Messages: ${state.messages.size}",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
