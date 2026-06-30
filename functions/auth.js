/**
 * 认证与记忆 API
 * POST /auth - 登录
 * PUT /auth - 注册
 * GET /auth/memory - 获取记忆
 * POST /auth/memory - 保存记忆
 */

export async function onRequestPost(context) {
  const { request, env } = context;
  
  // 设置 CORS 头
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, PUT, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  try {
    const url = new URL(request.url);
    const path = url.pathname;

    // 处理 OPTIONS 预检
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    // 登录
    if (path === '/auth') {
      return await handleLogin(request, env, corsHeaders);
    }
    
    // 注册
    if (path === '/auth/register') {
      return await handleRegister(request, env, corsHeaders);
    }

    // 获取记忆
    if (path === '/auth/memory' && request.method === 'GET') {
      return await handleGetMemory(request, env, corsHeaders);
    }

    // 保存记忆
    if (path === '/auth/memory' && request.method === 'POST') {
      return await handleSaveMemory(request, env, corsHeaders);
    }

    // 未知路径
    return new Response(
      JSON.stringify({ success: false, error: '未知的 API 路径' }),
      { status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );

  } catch (e) {
    console.error('Auth error:', e);
    return new Response(
      JSON.stringify({ success: false, error: e.message || '服务器错误' }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }
}

/**
 * 登录处理
 * 请求体: { username: string, password: string }
 */
async function handleLogin(request, env, corsHeaders) {
  const body = await request.json();
  const { username, password } = body;

  if (!username || !password) {
    return new Response(
      JSON.stringify({ success: false, error: '用户名和密码不能为空' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // 从 KV 获取用户数据
  const userKey = `user:${username}`;
  const userData = await env.HOPEAI_KV.get(userKey, 'json');

  if (!userData) {
    return new Response(
      JSON.stringify({ success: false, error: '账号不存在，请先注册' }),
      { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  if (userData.password !== password) {
    return new Response(
      JSON.stringify({ success: false, error: '密码错误' }),
      { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // 登录成功，返回用户信息（不含密码）
  const { password: _, ...safeUserData } = userData;
  return new Response(
    JSON.stringify({ success: true, user: safeUserData }),
    { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
  );
}

/**
 * 注册处理
 * 请求体: { username: string, password: string }
 */
async function handleRegister(request, env, corsHeaders) {
  const body = await request.json();
  const { username, password } = body;

  if (!username || !password) {
    return new Response(
      JSON.stringify({ success: false, error: '用户名和密码不能为空' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // 检查用户名格式（只能是字母数字下划线，3-20位）
  if (!/^[a-zA-Z0-9_]{3,20}$/.test(username)) {
    return new Response(
      JSON.stringify({ success: false, error: '用户名只能包含字母、数字、下划线，长度3-20位' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // 检查密码长度
  if (password.length < 6) {
    return new Response(
      JSON.stringify({ success: false, error: '密码至少6位' }),
      { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // 检查用户是否已存在
  const userKey = `user:${username}`;
  const existingUser = await env.HOPEAI_KV.get(userKey, 'json');

  if (existingUser) {
    return new Response(
      JSON.stringify({ success: false, error: '用户名已存在' }),
      { status: 409, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // 创建新用户
  const newUser = {
    username: username,
    password: password, // 实际生产环境应该哈希存储
    role: '专属编程导师',
    createdAt: new Date().toISOString(),
    historyTopics: [],
    customPrompt: `你现在是 ${username} 的专属AI助手。请保持极客风格，多用代码示例解答。`
  };

  await env.HOPEAI_KV.put(userKey, JSON.stringify(newUser));

  // 初始化用户记忆
  const memoryKey = `memory:${username}`;
  const initialMemory = {
    username: username,
    historyTopics: [],
    experience: [],
    preferences: {}
  };
  await env.HOPEAI_KV.put(memoryKey, JSON.stringify(initialMemory));

  // 返回用户信息（不含密码）
  const { password: _, ...safeUserData } = newUser;
  return new Response(
    JSON.stringify({ success: true, user: safeUserData, message: '注册成功！' }),
    { status: 201, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
  );
}

/**
 * 获取用户记忆
 * 请求头: X-Username: username
 */
async function handleGetMemory(request, env, corsHeaders) {
  const username = request.headers.get('X-Username');

  if (!username) {
    return new Response(
      JSON.stringify({ success: false, error: '请先登录' }),
      { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  const memoryKey = `memory:${username}`;
  const memory = await env.HOPEAI_KV.get(memoryKey, 'json');

  if (!memory) {
    // 返回空记忆
    return new Response(
      JSON.stringify({
        success: true,
        memory: {
          username: username,
          historyTopics: [],
          experience: [],
          preferences: {}
        }
      }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  return new Response(
    JSON.stringify({ success: true, memory }),
    { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
  );
}

/**
 * 保存用户记忆
 * 请求头: X-Username: username
 * 请求体: { historyTopics?: [], experience?: [], preferences?: {} }
 */
async function handleSaveMemory(request, env, corsHeaders) {
  const username = request.headers.get('X-Username');

  if (!username) {
    return new Response(
      JSON.stringify({ success: false, error: '请先登录' }),
      { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  const body = await request.json();
  const memoryKey = `memory:${username}`;

  // 获取现有记忆并合并
  const existingMemory = await env.HOPEAI_KV.get(memoryKey, 'json');
  const updatedMemory = {
    ...existingMemory,
    ...body,
    username: username, // 确保用户名不被覆盖
    updatedAt: new Date().toISOString()
  };

  await env.HOPEAI_KV.put(memoryKey, JSON.stringify(updatedMemory));

  return new Response(
    JSON.stringify({ success: true, message: '记忆已保存' }),
    { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
  );
}
