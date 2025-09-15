### How to connect posts from day 2 to day 1 topics

for example on day 1 (14-09) I had topic named as
"Gemini 3.0 Release Rumors"

and on day 2 (15-09) we have the post talking about
"Imagine they release Gemini 2.75 instead lol" Logically it is talking
about the gemini 3 and it's rofl, but we can't connect this post to
yesterdays topic because we does not offer post based analytics
so what should we do for it?
IDK at this time

Solution I can came up with is temporary embed this thing, search 
and topic, but it would be too computationally expensive, so I guess
I need to forgot about it at this time.


### Author Based Posts should be ordered and passed to LLM in a way

current flow:
Post 1 form Author B time 11
Post 2 form Author D time 23
Post 3 form Author A time 24
Post 4 form Author B time 41

Model does not have context who wrote this posts, so it can't 
normally understand the context why this post is ever written.
we can pass sorted by sources, and maybe model will increase it's ability
to understand context behind the things.