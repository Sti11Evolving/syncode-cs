typedef struct Node
{
    int value;
    struct Node *next;
} Node;

typedef Node *NodePtr;
typedef unsigned int NodeCount;

NodeCount count_nodes(NodePtr head);

int main(void)
{
    Node first = {3, 0};
    Node second = {5, 0};
    NodeCount total;

    first.next = &second;
    total = count_nodes(&first);

    return 0;
}

// Count the nodes in the linked list.
NodeCount count_nodes(NodePtr head)
{
