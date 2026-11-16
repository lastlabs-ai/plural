You find near-duplicate evaluation Tasks: two Tasks are near-duplicates when an agent
that handles one correctly would handle the other correctly for the same reason, with
nothing new tested. Different customer names or wording alone do not make Tasks
different; a different quantity, date or condition that changes the right answer
does.

You are given numbered Tasks. Return `groups`: each group is a list of two or more
numbers of Tasks that are near-duplicates of each other. Leave out every Task that
has no near-duplicate. Put each number in at most one group.
